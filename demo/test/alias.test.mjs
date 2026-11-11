// Unit tests of the browser port, without a model. Fictitious values only (tests/README.md).
// The comparison with the Python detector on many texts is parity.mjs.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  PERSON_FILE_KEYWORDS,
  TAGS,
  alignTokens,
  detect,
  detectRules,
  ibanIsValid,
  keywordKind,
  mask,
  mergeWindows,
  nirIsValid,
  resolveOverlaps,
  spansFromTokens,
  windows,
} from "../alias.js";

const tag = (name) => TAGS.indexOf(name);
const span = (e) => [e.type, e.start, e.end];

test("checksums", () => {
  assert.ok(ibanIsValid("FR76 3000 6000 0112 3456 7890 189"));
  assert.ok(!ibanIsValid("FR76 3000 6000 0112 3456 7890 188"));
  assert.ok(ibanIsValid("GB82 WEST 1234 5698 7654 32"));
  assert.ok(nirIsValid("1 85 05 78 006 084 91"));
  assert.ok(!nirIsValid("1 85 05 78 006 084 92"));
});

test("rules find the proven types", () => {
  const text =
    "Né le 12/03/1985, NIR 1 85 05 78 006 084 91, IBAN FR76 3000 6000 0112 3456 7890 189, " +
    "SSN 123-45-6789, DOB: July 2, 1969.";
  const found = detectRules(text).map((e) => [e.type, e.text]);
  assert.deepEqual(found, [
    ["BIRTH_DATE", "12/03/1985"],
    ["NATIONAL_ID", "1 85 05 78 006 084 91"],
    ["IBAN", "FR76 3000 6000 0112 3456 7890 189"],
    ["NATIONAL_ID", "123-45-6789"],
    ["BIRTH_DATE", "July 2, 1969"],
  ]);
});

test("a date without a birth keyword is left alone", () => {
  assert.deepEqual(detectRules("Facture du 12/03/2024."), []);
});

test("Unicode word boundaries: a keyword inside a word is not a keyword", () => {
  // "éné le" must not read as "né le": JavaScript's \b alone would accept it.
  assert.deepEqual(detectRules("Le pavé né le 12/03/1985").map((e) => e.text), ["12/03/1985"]);
  assert.deepEqual(detectRules("Le moulin éné le 12/03/1985"), []);
});

test("overlapping spans merge into the strongest type", () => {
  const text = "AB-0612345678-ZZ";
  const merged = resolveOverlaps([
    { type: "PHONE", start: 3, end: 13, text: text.slice(3, 13), score: 1 },
    { type: "IDENTIFIER", start: 0, end: 16, text, score: 1 },
  ]);
  assert.deepEqual(merged.map(span), [["PHONE", 0, 16]]);
  assert.equal(merged[0].text, text);
});

test("token offsets: prepended space, spaces, byte fallback", () => {
  const text = "Jean Dupont é";
  const tokens = ["▁Jean", "▁Du", "pont", "▁", "<0xC3>", "<0xA9>"];
  assert.deepEqual(alignTokens(text, tokens), [
    [0, 4],
    [4, 7],
    [7, 11],
    [11, 12],
    [12, 13],
    [12, 13],
  ]);
  assert.throws(() => alignTokens("abc", ["▁abd"]));
});

test("token offsets: a '▁' prepended after a newline belongs to the next character", () => {
  // The newline is an added token: the tokenizer starts a new segment after it, with a "▁".
  assert.deepEqual(alignTokens("61\nThe", ["▁", "6", "1", "\n", "▁The"]), [
    [0, 1],
    [0, 1],
    [1, 2],
    [2, 3],
    [3, 6],
  ]);
});

test("windows overlap by the stride", () => {
  const ids = Array.from({ length: 1000 }, (_, i) => i + 10);
  const offsets = ids.map((_, i) => [i, i + 1]);
  const parts = windows(ids, offsets, { bos: 1, eos: 2 });
  assert.deepEqual(
    parts.map((w) => [w.ids[1] - 10, w.ids.length - 2]),
    [
      [0, 510],
      [382, 510],
      [764, 236],
    ],
  );
  assert.deepEqual(parts[0].offsets[0], [0, 0]);
});

test("windows: each token keeps the most central window's tag", () => {
  const offsets = [[0, 0], [0, 1], [1, 2], [2, 3], [0, 0]];
  const merged = mergeWindows([
    { offsets, tags: [0, 1, 1, 1, 0] },
    { offsets: [[0, 0], [2, 3], [3, 4], [0, 0]], tags: [0, 2, 0, 0] },
  ]);
  assert.deepEqual(merged, [
    [0, 1, 1],
    [1, 2, 1],
    [2, 3, 1],
    [3, 4, 0],
  ]);
});

test("B/I runs become trimmed spans", () => {
  const text = "Jean Dupont habite";
  const tokens = [
    [0, 4, tag("B-PERSON")],
    [4, 11, tag("I-PERSON")],
    [11, 18, tag("O")],
  ];
  assert.deepEqual(spansFromTokens(text, tokens).map(span), [["PERSON", 0, 11]]);
});

test("rules and model together, then masking with stable aliases", async () => {
  const text = "Jean Dupont, né le 12/03/1985. Signé : jean dupont.";
  // A fake tokenizer (words and punctuation, spaces as "▁") and a fake model tagging
  // "Jean Dupont" in any case.
  const tokens = `▁${text.replaceAll(" ", "▁")}`.match(/▁?[^▁.,]+|[.,]/gu);
  const fake = {
    tokenize: () => ({ ids: tokens.map((_, i) => i + 10), tokens }),
    predict: async (ids) =>
      ids.map((id) => {
        const word = tokens[id - 10]?.replace("▁", "").toLowerCase();
        if (word === "jean") return tag("B-PERSON");
        if (word === "dupont") return tag("I-PERSON");
        return 0;
      }),
    bos: 1,
    eos: 2,
  };
  const entities = await detect(text, fake);
  const result = mask(text, entities);
  assert.equal(result.masked, "[PERSON_1], né le [BIRTH_DATE_1]. Signé : [PERSON_1].");
  assert.deepEqual(result.report, { PERSON: 2, BIRTH_DATE: 1, total: 3 });
});

test("an alias already in the text is never handed out", () => {
  const text = "[PERSON_1] a écrit à Jean Dupont.";
  const result = mask(text, [{ type: "PERSON", start: 21, end: 32, text: "Jean Dupont", score: 1 }]);
  assert.equal(result.masked, "[PERSON_1] a écrit à [PERSON_2].");
});

test("identifiers keep their keyword; variant 3 keeps a person's file only", async () => {
  assert.equal(keywordKind("Adhérent"), "adherent");
  assert.equal(keywordKind("réf."), "ref");
  const text = "Objet : dossier n° 2024/00421. Commande n° CMD-2024-118.";
  // A model that finds nothing: one token for the whole text, tagged O.
  const nothing = {
    tokenize: (t) => ({ ids: [10], tokens: [`▁${t.replaceAll(" ", "▁")}`] }),
    predict: async (ids) => ids.map(() => 0),
    bos: 1,
    eos: 2,
  };
  const v3 = await detect(text, nothing, PERSON_FILE_KEYWORDS);
  assert.deepEqual(v3.map((e) => [e.type, e.text]), [["IDENTIFIER", "2024/00421"]]);
});
