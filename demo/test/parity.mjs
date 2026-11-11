// Compares the browser port (demo/alias.js) with the Python detector on the cases written by
// parity_cases.py: token ids, token offsets and rule spans must be identical; with --model, the
// full detector (rules + ONNX model through transformers.js) must give the same spans on at
// least 99 % of the texts (ONNX Runtime and PyTorch round floats differently).
//
//   node demo/test/parity.mjs --cases cases.json --tokenizer Gabrielkph/alias-mmbert-small
//   node demo/test/parity.mjs --cases cases.json --tokenizer <folder> --model <folder>
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { parseArgs } from "node:util";

import { AutoModelForTokenClassification, AutoTokenizer, Tensor, env } from "@huggingface/transformers";

import { RULE_TYPES, TAGS, alignTokens, detect, detectRules } from "../alias.js";

const { values: args } = parseArgs({
  options: {
    cases: { type: "string" },
    tokenizer: { type: "string" },
    model: { type: "string" },
  },
});

function source(name) {
  // A local folder is loaded as a local model; anything else is a Hugging Face id.
  if (name && existsSync(name)) {
    env.allowLocalModels = true;
    env.localModelPath = path.dirname(path.resolve(name));
    return path.basename(path.resolve(name));
  }
  env.allowLocalModels = false;
  return name;
}

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const cases = JSON.parse(readFileSync(args.cases, "utf-8"));
const tokenizer = await AutoTokenizer.from_pretrained(source(args.tokenizer));
const encode = (text) => tokenizer._tokenizer.encode(text, { add_special_tokens: false });

let detector = null;
if (args.model) {
  const model = await AutoModelForTokenClassification.from_pretrained(source(args.model), {
    dtype: "fp32",
    device: "cpu",
  });
  if (TAGS.some((tag, i) => model.config.id2label[i] !== tag)) throw new Error("model labels");
  detector = {
    tokenize: (text) => {
      const { ids, tokens } = encode(text);
      return { ids, tokens };
    },
    predict: async (ids) => {
      const shape = [1, ids.length];
      const { logits } = await model({
        input_ids: new Tensor("int64", BigInt64Array.from(ids, BigInt), shape),
        attention_mask: new Tensor("int64", new BigInt64Array(ids.length).fill(1n), shape),
      });
      const [, length, classes] = logits.dims;
      return Array.from({ length }, (_, t) => {
        let best = 0;
        for (let c = 1; c < classes; c++) {
          if (logits.data[t * classes + c] > logits.data[t * classes + best]) best = c;
        }
        return best;
      });
    },
    bos: tokenizer.convert_tokens_to_ids("<bos>"),
    eos: tokenizer.convert_tokens_to_ids("<eos>"),
  };
}

const failures = { ids: [], offsets: [], rules: [], detector: [] };
for (const [index, c] of cases.entries()) {
  const { ids, tokens } = encode(c.text);
  if (!same(ids, c.ids)) failures.ids.push(index);
  let offsets = null;
  try {
    offsets = alignTokens(c.text, tokens);
  } catch (error) {
    offsets = String(error);
  }
  if (!same(offsets, c.offsets)) failures.offsets.push(index);
  const rules = detectRules(c.text)
    .filter((e) => RULE_TYPES.has(e.type))
    .map((e) => [e.type, e.start, e.end]);
  if (!same(rules, c.rules)) failures.rules.push({ index, js: rules, python: c.rules });
  if (detector && c.detector) {
    const found = (await detect(c.text, detector)).map((e) => [e.type, e.start, e.end]);
    if (!same(found, c.detector)) failures.detector.push({ index, js: found, python: c.detector });
  }
}

const n = cases.length;
console.log(`${n} texts`);
console.log(`token ids differ: ${failures.ids.length} ${JSON.stringify(failures.ids.slice(0, 10))}`);
console.log(`offsets differ: ${failures.offsets.length} ${JSON.stringify(failures.offsets.slice(0, 10))}`);
console.log(`rule spans differ: ${failures.rules.length}`);
for (const f of failures.rules.slice(0, 5)) console.log("  ", JSON.stringify(f));
let ok = !failures.ids.length && !failures.offsets.length && !failures.rules.length;
if (detector) {
  const agreement = 1 - failures.detector.length / n;
  console.log(`detector spans differ: ${failures.detector.length} (agreement ${(100 * agreement).toFixed(1)} %)`);
  for (const f of failures.detector.slice(0, 10)) console.log("  ", JSON.stringify(f));
  ok = ok && agreement >= 0.99;
}
console.log(ok ? "PARITY OK" : "PARITY FAILED");
process.exit(ok ? 0 : 1);
