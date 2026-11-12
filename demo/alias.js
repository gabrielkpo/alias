// Alias in the browser: the Python detector of `src/alias_pii`, ported function by function so
// the demo masks a text without it ever leaving the page. Pure functions, no dependency: the page
// (app.js) brings the tokenizer and the ONNX model, the tests (demo/test) run it under Node.
//
// Python counterparts: entities.resolve_overlaps, rules.RuleDetector, validators, tagging
// (merge_windows, spans_from_tokens), train.TrainedDetector (windows), detector.RulesAndModel,
// masking (AliasTable, mask). demo/test/parity.mjs checks both give the same spans.
//
// Known differences, kept small on purpose and checked by the parity test:
// - offsets count UTF-16 units, as JavaScript strings do (Python counts code points);
// - the rules' phone matcher (libphonenumber) is not ported: the detector drops the rules' phones
//   before merging overlaps anyway; a phone is keyed for its alias by its digits ("+33" for a
//   leading 0) instead of E.164;
// - digits are ASCII digits.

export const TYPES = [
  "PERSON",
  "ADDRESS",
  "EMAIL",
  "PHONE",
  "IBAN",
  "NATIONAL_ID",
  "BIRTH_DATE",
  "IDENTIFIER",
];

// Model output ids, as tagging.TAGS: O, then B- and I- for each type.
export const TAGS = ["O", ...TYPES.flatMap((t) => [`B-${t}`, `I-${t}`])];

const PRIORITY = {
  IBAN: 70,
  NATIONAL_ID: 60,
  EMAIL: 50,
  PHONE: 40,
  BIRTH_DATE: 30,
  PERSON: 20,
  ADDRESS: 20,
  IDENTIFIER: 10,
};

// The rules' types the detector keeps (detector.RULE_TYPES): proven by a checksum or a keyword.
export const RULE_TYPES = new Set(["IBAN", "NATIONAL_ID", "BIRTH_DATE"]);

// detector.PERSON_FILE_KEYWORDS: the rules' identifiers kept by variant 3 (docs/DETECTOR.md).
export const PERSON_FILE_KEYWORDS = new Set([
  "dossier", "contrat", "client", "patient", "adherent", "matricule", "sinistre", "passeport",
  "permis", "file", "claim", "customer", "passport", "licence", "license", "employee", "member",
  "membership",
]); // prettier-ignore

// The keywords the detector uses by default (detector.RulesAndModel's id_keywords).
export const ID_KEYWORDS = PERSON_FILE_KEYWORDS;

/** detector.RulesAndModel._kept: a rule span the detector adds to the model's. */
export function keptRule(e, idKeywords = ID_KEYWORDS) {
  return RULE_TYPES.has(e.type) || (e.type === "IDENTIFIER" && idKeywords.has(e.kind));
}

function entity(type, text, start, end, source = "rules", kind = null) {
  return { type, start, end, text: text.slice(start, end), score: 1.0, source, kind };
}

// ---------------------------------------------------------------- overlaps (entities.py)

function stronger(a, b) {
  // Python max() over (priority, length, score): the first maximal element wins.
  const ka = [PRIORITY[a.type], a.end - a.start, a.score];
  const kb = [PRIORITY[b.type], b.end - b.start, b.score];
  for (let i = 0; i < 3; i++) if (kb[i] !== ka[i]) return kb[i] > ka[i] ? b : a;
  return a;
}

function mergeGroup(group) {
  const best = group.reduce(stronger);
  const start = Math.min(...group.map((e) => e.start));
  const end = Math.max(...group.map((e) => e.end));
  if (start === best.start && end === best.end) return best;
  const chars = new Array(end - start).fill("");
  for (const e of group) {
    for (let i = 0; i < e.end - e.start; i++) chars[e.start - start + i] = e.text[i];
  }
  return { ...best, start, end, text: chars.join("") };
}

export function resolveOverlaps(entities) {
  const sorted = [...entities].sort((a, b) => a.start - b.start || a.end - b.end);
  const merged = [];
  let group = [];
  for (const e of sorted) {
    if (group.length && e.start >= Math.max(...group.map((g) => g.end))) {
      merged.push(mergeGroup(group));
      group = [];
    }
    group.push(e);
  }
  if (group.length) merged.push(mergeGroup(group));
  return merged;
}

// ---------------------------------------------------------------- validators.py

const IBAN_LENGTHS = {
  AT: 20, BE: 16, CH: 21, DE: 22, DK: 18, ES: 24, FI: 18, FR: 27, GB: 22, GR: 27, IE: 22,
  IT: 27, LU: 20, MC: 27, NL: 18, NO: 15, PL: 28, PT: 25, SE: 24,
}; // prettier-ignore

export function compact(value) {
  return value.replace(/[\s.\-\u00ad\u200b\u200c\u200d\u2060\ufeff]/gu, "").toUpperCase();
}

export function ibanIsValid(value) {
  const iban = compact(value);
  if (!/^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$/.test(iban)) return false;
  const expected = IBAN_LENGTHS[iban.slice(0, 2)];
  if (expected !== undefined && iban.length !== expected) return false;
  const moved = iban.slice(4) + iban.slice(0, 4);
  let rest = 0;
  for (const c of moved) {
    const digits = String(parseInt(c, 36));
    for (const d of digits) rest = (rest * 10 + Number(d)) % 97;
  }
  return rest === 1;
}

export function nirIsValid(value) {
  const nir = compact(value);
  if (!/^[1-478][0-9]{4}(?:[0-9]{2}|2[AB])[0-9]{6}[0-9]{2}$/.test(nir)) return false;
  const month = Number(nir.slice(3, 5));
  if (!((month >= 1 && month <= 12) || (month >= 20 && month <= 42) || (month >= 50 && month <= 99)))
    return false;
  const body = nir.slice(0, 13).replaceAll("2A", "19").replaceAll("2B", "18");
  return 97 - (Number(body) % 97) === Number(nir.slice(13));
}

// ---------------------------------------------------------------- rules.py

// Python's \w, \b and (?!\w) are Unicode-aware; JavaScript's are ASCII-only even with the u flag.
const W = "[\\p{L}\\p{N}_]";
const B = `(?:(?<=${W})(?!${W})|(?<!${W})(?=${W}))`; // \b

// Possessive quantifiers of the Python pattern dropped: no backtracking choice changes the match.
const EMAIL = new RegExp(
  `(?<![\\p{L}\\p{N}_.+\\-])[\\p{L}\\p{N}_.+\\-]+@[\\p{L}\\p{N}_\\-]+(?:\\.[\\p{L}\\p{N}_\\-]+)*` +
    `\\.[\\p{L}\\p{Nl}\\p{No}]{2,}(?!${W})`,
  "gu",
);

const SEP = "[ .\\-]?";
const NIR = new RegExp(
  `(?<!${W})[1-478](?:${SEP}[0-9]){4}${SEP}(?:[0-9]${SEP}[0-9]|2${SEP}[ABab])(?:${SEP}[0-9]){6}` +
    `${SEP}[0-9]${SEP}[0-9](?!${W})`,
  "gu",
);
const US_SSN = /(?<![0-9-])(?!000|666|9[0-9][0-9])[0-9]{3}([- ])(?!00)[0-9]{2}\1(?!0000)[0-9]{4}(?![0-9-])/gu;
const UK_NINO = new RegExp(
  "(?<![A-Za-z0-9])(?!BG|GB|NK|KN|TN|NT|ZZ)[A-CEGHJ-PR-TW-Z][A-CEGHJ-NPR-TW-Z]" +
    " ?[0-9]{2} ?[0-9]{2} ?[0-9]{2} ?[A-D](?![A-Za-z0-9])",
  "giu",
);
const IBAN_START = /(?<![A-Za-z0-9])[A-Za-z]{2}[0-9]{2}/gu;

const NUMBER_WORD = `(?:n[°º]\\.?|#|(?:number|num[ée]ro|num\\.|no\\.|nr\\.|num|no|nr|id)(?!${W}))`;
const ID_KEYWORD =
  "(?:dossier|contrat|client|r[ée]f[ée]rence|r[ée]f\\.?|facture|police|patient|adh[ée]rent" +
  "|matricule|sinistre|commande|compte|abonn[ée]|badge|passeport|permis" +
  "|case|file|contract|customer|reference|invoice|policy|member(?:ship)?|employee|account" +
  "|claim|order|ticket|passport|licen[cs]e|id)";
const FILLER = "(?:(?:is|was|est|était|=)\\s+)?(?:(?:le|la|the)\\s+)?";
const IDENTIFIER = new RegExp(
  `(?:${B}${NUMBER_WORD}\\s*(?:de\\s+|du\\s+|d['’]\\s*|of\\s+)?)?${B}(?<keyword>${ID_KEYWORD})(?!${W})` +
    `(?:\\s+(?:\\p{L}{2,20}\\s+)?${NUMBER_WORD})?\\s*(?:[:#]\\s*)?${FILLER}` +
    "(?<value>[A-Z0-9](?:[A-Z0-9/_.\\-]*[A-Z0-9])?)",
  "giud",
);

const MONTHS =
  "(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[ûu]t|septembre|octobre|novembre" +
  "|d[ée]cembre|january|february|march|april|may|june|july|august|september|october" +
  "|november|december|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)\\.?";
const DATE =
  "(?:[0-9]{1,2}[/.\\-][0-9]{1,2}[/.\\-](?:[0-9]{4}|[0-9]{2})" +
  "|[0-9]{4}-[0-9]{2}-[0-9]{2}" +
  `|[0-9]{1,2}(?:er|st|nd|rd|th)?\\s+(?:of\\s+)?${MONTHS}\\s+[0-9]{4}` +
  `|${MONTHS}\\s+[0-9]{1,2}(?:st|nd|rd|th)?,?\\s+[0-9]{4})`;
const BIRTH_KEYWORD =
  `(?:${B}n[ée]e?(?:\\(e\\))?\\s+le` +
  `|${B}(?:date\\s+de\\s+)?naiss(?:ance|\\.)(?:\\s+d[ée]clar[ée]e)?` +
  `|${B}date\\s+of\\s+birth|${B}birth\\s*date|${B}d\\.?o\\.?b${B}\\.?|${B}born(?:\\s+on)?)`;
const BIRTH_DATE = new RegExp(
  `${BIRTH_KEYWORD}[\\s:(|\\-–—]*(?:(?:is|was|as|est|le|on)\\s+)?` +
    `(?<value>(?<![0-9])${DATE})(?![0-9]|${W})`,
  "giud",
);
const BIRTH_DATE_BEFORE = new RegExp(
  `(?<![0-9]|${W})(?<value>${DATE})\\s*[:\\-–—]\\s*${BIRTH_KEYWORD}`,
  "giud",
);

function* matches(pattern, text) {
  pattern.lastIndex = 0;
  let m;
  while ((m = pattern.exec(text)) !== null) {
    if (m[0] === "") pattern.lastIndex++;
    yield m;
  }
}

const ASCII_ALNUM = /^[A-Za-z0-9]$/;
const ALNUM = /^[\p{L}\p{N}]$/u;

function* ibans(text) {
  for (const m of matches(IBAN_START, text)) {
    const ends = [];
    let i = m.index;
    while (i < text.length && ends.length < 34) {
      const char = text[i];
      if (ASCII_ALNUM.test(char)) {
        i += 1;
        ends.push(i);
      } else if ((char === " " || char === "-") && i + 1 < text.length && ASCII_ALNUM.test(text[i + 1])) {
        i += 1;
      } else {
        break;
      }
    }
    const country = m[0].slice(0, 2).toUpperCase();
    const expected = IBAN_LENGTHS[country];
    const lengths = expected ? [expected] : [];
    if (!expected) for (let n = ends.length; n > 14; n--) lengths.push(n);
    for (const length of lengths) {
      if (length > ends.length) continue;
      const end = ends[length - 1];
      if (end < text.length && ALNUM.test(text[end])) continue;
      if (ibanIsValid(text.slice(m.index, end))) {
        yield entity("IBAN", text, m.index, end, "rules", country);
        break;
      }
    }
  }
}

function* nationalIds(text) {
  for (const m of matches(NIR, text))
    if (nirIsValid(m[0])) yield entity("NATIONAL_ID", text, m.index, m.index + m[0].length, "rules", "FR_NIR");
  for (const m of matches(US_SSN, text))
    yield entity("NATIONAL_ID", text, m.index, m.index + m[0].length, "rules", "US_SSN");
  for (const m of matches(UK_NINO, text))
    yield entity("NATIONAL_ID", text, m.index, m.index + m[0].length, "rules", "UK_NINO");
}

function* emails(text) {
  for (const m of matches(EMAIL, text)) yield entity("EMAIL", text, m.index, m.index + m[0].length);
}

function* identifiers(text) {
  for (const m of matches(IDENTIFIER, text)) {
    const value = m.groups.value;
    if (value.length >= 4 && /[0-9]/.test(value)) {
      const [start, end] = m.indices.groups.value;
      yield entity("IDENTIFIER", text, start, end, "rules", keywordKind(m.groups.keyword));
    }
  }
}

/** rules.keyword_kind: "Adhérent" -> "adherent", "réf." -> "ref". */
export function keywordKind(keyword) {
  return keyword.toLowerCase().normalize("NFKD").replace(/\p{Mn}/gu, "").replace(/\.+$/u, "");
}

function* birthDates(text) {
  for (const pattern of [BIRTH_DATE, BIRTH_DATE_BEFORE]) {
    for (const m of matches(pattern, text)) {
      const [start, end] = m.indices.groups.value;
      yield entity("BIRTH_DATE", text, start, end);
    }
  }
}

// rules.SPACES and rules.INVISIBLE: typographic spaces read as a space, invisible characters
// skipped, so a value written with them does not stay readable.
const SPACES = new Set(
  "\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000",
);
const INVISIBLE = new Set("\u00ad\u200b\u200c\u200d\u2060\ufeff");
const TYPOGRAPHY = new RegExp(`[${[...SPACES, ...INVISIBLE].join("")}]`, "u");

/** rules.shadow: the text as the rules read it, and each position's offset in the original. */
export function shadow(text) {
  let read = "";
  const origin = [];
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (INVISIBLE.has(char)) continue;
    read += SPACES.has(char) ? " " : char;
    origin.push(i);
  }
  origin.push(text.length);
  return [read, origin];
}

function findRaw(text) {
  return [...emails(text), ...ibans(text), ...nationalIds(text), ...identifiers(text), ...birthDates(text)];
}

/** rules.RuleDetector.find, without the phone matcher: every rule's spans, not merged yet. */
export function findRules(text) {
  if (!TYPOGRAPHY.test(text)) return findRaw(text);
  const [read, origin] = shadow(text);
  return findRaw(read).map((e) => {
    const start = origin[e.start];
    const end = origin[e.end - 1] + 1;
    return { ...e, start, end, text: text.slice(start, end) };
  });
}

/** rules.RuleDetector.detect, without the phone matcher. */
export function detectRules(text) {
  return resolveOverlaps(findRules(text));
}

// ---------------------------------------------------------------- tokens and windows

/**
 * Character offsets of each token, as the Python fast tokenizer's offset mapping.
 *
 * The mmBERT tokenizer replaces spaces with "▁" and splits before each "▁"; unknown characters
 * fall back to one token per UTF-8 byte ("<0xE2>"). Each token is matched against that
 * normalised text, which maps back to the original characters one to one, and byte tokens all
 * get the offsets of their character. The tokenizer also prepends a "▁" to every segment that
 * does not start with one (the text, and what follows an added token such as a newline): that
 * "▁" is in no character, so it takes the offsets of the character after it, as in Python.
 */
export function alignTokens(text, tokens) {
  const normalized = [];
  for (let i = 0; i < text.length; ) {
    const width = text.codePointAt(i) > 0xffff ? 2 : 1;
    const char = text.slice(i, i + width);
    normalized.push({ char: char === " " ? "▁" : char, start: i, end: i + width });
    i += width;
  }
  const offsets = [];
  let pos = 0;
  let pending = []; // byte tokens of the character being rebuilt
  let need = 0;
  for (let token of tokens) {
    const byte = /^<0x([0-9A-F]{2})>$/.exec(token);
    if (byte) {
      const value = parseInt(byte[1], 16);
      if (!pending.length) need = value >= 0xf0 ? 4 : value >= 0xe0 ? 3 : value >= 0xc0 ? 2 : 1;
      pending.push(offsets.length);
      offsets.push(null);
      if (pending.length === need) {
        const point = normalized[pos++];
        if (!point) throw new Error("token alignment ran past the text");
        for (const k of pending) offsets[k] = [point.start, point.end];
        pending = [];
      }
      continue;
    }
    let chars = Array.from(token);
    if (chars[0] === "▁" && normalized[pos]?.char !== "▁") {
      chars = chars.slice(1); // the prepended "▁"
      if (!chars.length) {
        const next = normalized[pos];
        offsets.push(next ? [next.start, next.end] : [text.length, text.length]);
        continue;
      }
      token = chars.join("");
    }
    const slice = normalized.slice(pos, pos + chars.length);
    if (slice.map((p) => p.char).join("") !== token) {
      throw new Error(`token alignment failed at character ${normalized[pos]?.start ?? text.length}`);
    }
    offsets.push([slice[0].start, slice[slice.length - 1].end]);
    pos += chars.length;
  }
  if (pending.length || pos !== normalized.length) throw new Error("token alignment incomplete");
  return offsets;
}

/**
 * Overlapping windows as the Python tokenizer's `return_overflowing_tokens` with
 * max_length=512 and stride=128: 510 text tokens each, the next one starting 128 tokens before
 * the previous one ends, a begin and an end token around each (offsets [0, 0]).
 */
export function windows(ids, offsets, { maxLength = 512, stride = 128, bos, eos }) {
  const size = maxLength - 2;
  const result = [];
  for (let start = 0; ; start += size - stride) {
    const end = Math.min(start + size, ids.length);
    result.push({
      ids: [bos, ...ids.slice(start, end), eos],
      offsets: [[0, 0], ...offsets.slice(start, end), [0, 0]],
    });
    if (end >= ids.length) break;
  }
  return result;
}

/** tagging.merge_windows: each token keeps the tag of the window where it is most central. */
export function mergeWindows(predicted) {
  const best = new Map();
  for (const { offsets, tags } of predicted) {
    const real = [];
    offsets.forEach(([s, e], i) => {
      if (s !== e) real.push(i);
    });
    real.forEach((i, rank) => {
      const margin = Math.min(rank, real.length - 1 - rank);
      const key = `${offsets[i][0]},${offsets[i][1]}`;
      const seen = best.get(key);
      if (seen === undefined || margin > seen.margin) {
        best.set(key, { start: offsets[i][0], end: offsets[i][1], margin, tag: tags[i] });
      }
    });
  }
  return [...best.values()]
    .sort((a, b) => a.start - b.start || a.end - b.end)
    .map(({ start, end, tag }) => [start, end, tag]);
}

const SPACE = /\s/u;

/** tagging.spans_from_tokens: B/I runs of one label become one span, trimmed of spaces. */
export function spansFromTokens(text, tokens) {
  const entities = [];
  let open = null; // [label, start, end]
  const close = () => {
    if (!open) return;
    let [label, start, end] = open;
    while (start < end && SPACE.test(text[start])) start++;
    while (end > start && SPACE.test(text[end - 1])) end--;
    if (start < end) entities.push(entity(label, text, start, end, "model"));
  };
  for (const [start, end, tagId] of tokens) {
    const tag = TAGS[tagId];
    if (tag === "O") {
      close();
      open = null;
      continue;
    }
    const [prefix, label] = [tag.slice(0, 1), tag.slice(2)];
    if (prefix === "I" && open && open[0] === label) {
      open[2] = end;
    } else {
      close();
      open = [label, start, end];
    }
  }
  close();
  return entities;
}

/**
 * train.TrainedDetector.detect. `tokenize(text)` returns `{ ids, tokens }` without special
 * tokens; `predict(ids)` returns one tag id per id of a window (argmax of the logits).
 */
export async function detectModel(text, { tokenize, predict, bos, eos }) {
  if (!text) return [];
  const { ids, tokens } = tokenize(text);
  const offsets = alignTokens(text, tokens);
  const predicted = [];
  for (const window of windows(ids, offsets, { bos, eos })) {
    predicted.push({ offsets: window.offsets, tags: await predict(window.ids) });
  }
  return spansFromTokens(text, mergeWindows(predicted));
}

/** detector.RulesAndModel.detect: the model's spans plus the rules' kept spans. */
export async function detect(text, model, idKeywords = ID_KEYWORDS) {
  // Raw rule spans filtered before merging, as in Python: a dropped type cannot absorb a kept one.
  const rules = findRules(text).filter((e) => keptRule(e, idKeywords));
  return resolveOverlaps([...rules, ...(await detectModel(text, model))]);
}

// ---------------------------------------------------------------- masking.py

const ALIAS = new RegExp(`\\[\\s*(${TYPES.join("|")})_([0-9]+)\\s*\\]`, "gu");

export function normalize(e) {
  if (e.type === "PHONE") {
    // Python parses with libphonenumber (region FR) to E.164; digits are a close stand-in.
    const digits = e.text.replace(/[^0-9+]/gu, "");
    if (digits.startsWith("+")) return `+${digits.slice(1).replaceAll("+", "")}`;
    if (digits.startsWith("00")) return `+${digits.slice(2)}`;
    if (digits.startsWith("0")) return `+33${digits.slice(1)}`;
    return `+33${digits}`;
  }
  if (e.type === "IBAN" || e.type === "NATIONAL_ID") return compact(e.text);
  const visible = e.text.replace(/[\u00ad\u200b\u200c\u200d\u2060\ufeff]/gu, "");
  // An e-mail only ignores case, an identifier case and spacing: a dot or dash makes another one.
  if (e.type === "EMAIL") return visible.normalize("NFC").trim().toUpperCase().toLowerCase();
  if (e.type === "IDENTIFIER") return visible.toUpperCase().split(/\s+/u).filter(Boolean).join(" ");
  // Upper then lower case is closer to Python's casefold than lower case alone (ß -> ss).
  const folded = e.text.toUpperCase().toLowerCase().normalize("NFKD").replace(/\p{Mn}/gu, "");
  return folded.split(/\s+/u).filter(Boolean).join(" ");
}

const canonical = (m) => `[${m[1]}_${parseInt(m[2], 10)}]`;

/**
 * masking.mask with a fresh alias table: masked text, spans with their alias, counts, and what
 * `restore` needs. `values` (alias -> the value it hides) stays in the page's memory only: it
 * is never part of the report, the spans or a request.
 */
export function mask(text, entities) {
  const literals = new Set([...text.matchAll(ALIAS)].map(canonical));
  const byKey = new Map();
  const values = new Map();
  const counters = {};
  const aliasFor = (e) => {
    const key = `${e.type}\u0000${normalize(e)}`;
    if (!byKey.has(key)) {
      let alias;
      do {
        counters[e.type] = (counters[e.type] || 0) + 1;
        alias = `[${e.type}_${counters[e.type]}]`;
      } while (literals.has(alias));
      byKey.set(key, alias);
      values.set(alias, e.text);
    }
    return byKey.get(key);
  };
  const parts = [];
  const spans = [];
  const aliases = [];
  let cursor = 0;
  for (const e of resolveOverlaps(entities)) {
    const alias = aliasFor(e);
    parts.push(text.slice(cursor, e.start), alias);
    spans.push({ type: e.type, start: e.start, end: e.end, alias });
    if (!aliases.includes(alias)) aliases.push(alias);
    cursor = e.end;
  }
  parts.push(text.slice(cursor));
  const report = {};
  for (const s of spans) report[s.type] = (report[s.type] || 0) + 1;
  report.total = spans.length;
  return { masked: parts.join(""), entities: spans, report, values, aliases, literals };
}

/**
 * masking.restore for one exchange: puts back the values of the aliases `mask` wrote into the
 * text sent to the LLM. An alias that was already literal in the input is never restored (it
 * cannot be told apart from a real one); an alias the answer invents stays as it is. Returns
 * the text, the aliases restored, those sent but absent from the answer (`missing`) and the
 * alias-shaped tokens left as they are (`unknown`).
 */
export function restore(answer, result) {
  const allowed = new Set(result.aliases.filter((a) => !result.literals.has(a)));
  const restored = [];
  const unknown = [];
  const text = answer.replace(ALIAS, (...m) => {
    const alias = canonical(m);
    if (!allowed.has(alias)) {
      if (!result.literals.has(alias) && !unknown.includes(alias)) unknown.push(alias);
      return m[0];
    }
    if (!restored.includes(alias)) restored.push(alias);
    return result.values.get(alias);
  });
  const missing = [...allowed].filter((a) => !restored.includes(a));
  return { text, restored, missing, unknown };
}
