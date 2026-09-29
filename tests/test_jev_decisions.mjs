// Throwaway live smoke test for harness/.pi/extensions/jev-core.ts's pure
// helpers. Builds ONE real Agent-1-shaped request (candidates + choice/noul
// questions matching tools/jev_questions.py's QUESTION_SET_AGENT1 shape), sends
// it to the real Decisions API, and prints only the answers + cost -- never the
// API key. Imports jev-core.ts directly (not jev-decisions.ts), since the
// latter's top-level imports of @earendil-works/pi-ai and
// @earendil-works/pi-coding-agent only resolve inside pi's extension host. Run:
//   node --experimental-strip-types tests/test_jev_decisions.mjs

import { callDecisions, extractAnswers } from "../harness/.pi/extensions/jev-core.ts";

const MODEL = process.env.JEV_MODEL || "typesafe/jev-1.13";

// Photo text lines an Agent-1-style generous extractor would have pulled off one
// image, plus the candidate strings it flagged as plausible OEM-number-like.
const state = {
	make: "Hyundai",
	photo_text_lines: [
		"HYUNDAI GENUINE PARTS",
		"92501-C1000",
		"E11 03124",
		"MADE IN KOREA",
	],
};

const candidates = ["92501-C1000", "E11 03124", "20240315"];

const questions = {
	genuine_part_number: {
		type: "choice",
		instructions: "Which of these candidate strings is the genuine OEM part number for a Hyundai part?",
		criteria: Object.fromEntries(candidates.map((c) => [c, ""])),
	},
	is_valid_oem_format: {
		type: "noul",
		instructions: "is this candidate string formatted like a real OEM part number for the stated make?",
		criteria: {
			true: "The string matches the format Hyundai OEM part numbers use.",
			false:
				"The string does not look like a real Hyundai OEM part number " +
				"(wrong length, wrong character set, looks like a SKU/barcode, etc).",
		},
	},
};

try {
	const response = await callDecisions(MODEL, state, questions);
	const { answers, cost } = extractAnswers(response);
	console.log("answers:", JSON.stringify(answers, null, 2));
	console.log(`usage.cost: $${cost?.toFixed(6) ?? "unknown"}`);
} catch (err) {
	console.error(`jev_decide smoke test failed: ${err.message}`);
	process.exitCode = 1;
}
