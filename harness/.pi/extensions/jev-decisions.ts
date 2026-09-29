/**
 * pi extension exposing TypeSafe Jev (OpenRouter's Decisions API) as a `jev_decide`
 * tool, so agents can hand a state + typed questions to a decision model instead
 * of judging things themselves in free text.
 *
 * This file is pi-wiring ONLY: tool registration, parameter schemas, and error
 * text for the tool-call boundary. All the actual request/parsing logic (fetch,
 * retries, .env resolution) lives in ./jev-core.ts, which is dependency-free and
 * importable outside pi's runtime -- see tests/test_jev_decisions.mjs, which
 * imports jev-core.ts directly rather than this file, since this file's top-level
 * imports of @earendil-works/pi-ai and @earendil-works/pi-coding-agent only
 * resolve inside pi's extension host.
 *
 * Which agent step should call this tool, and what to do with the answer, lives
 * in that agent's own instructions file (agents/agent1_instructions_v9_jev.md and
 * its mirror in .pi/agents/agent1-part-reader.md) — NOT here. Restating those
 * rules in this tool's description was tried once already for a different tool
 * (see agent2_instructionsv6.md's changelog on ebay_search's description drifting
 * from Agent 2's own Resolve rule) and the two copies silently went out of sync.
 * This tool only describes the wire protocol; it never paraphrases agent policy.
 */

import { Type } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
	callDecisions,
	DEFAULT_MODEL,
	JevAuthError,
	JevPaymentError,
	parseEnvFile,
	resolveApiKey,
	buildRequest,
	extractAnswers,
} from "./jev-core.ts";

// Re-exported so any existing importer of this file's helpers keeps working --
// the implementations now live in jev-core.ts.
export { parseEnvFile, resolveApiKey, buildRequest, callDecisions, extractAnswers };
export { JevAPIError, JevAuthError, JevPaymentError } from "./jev-core.ts";

export default function (pi: ExtensionAPI) {
	pi.registerTool({
		name: "jev_decide",
		label: "Jev Decision",
		description:
			"Send a state (the thing to evaluate) and one or more typed questions to " +
			"TypeSafe Jev (OpenRouter's Decisions API) and get back structured answers " +
			"with a probability-backed value for each -- no parsing a model's free-text " +
			"reasoning required. `questions` is a dict of question-key -> question spec " +
			"({type: 'noul'|'choice'|'score', instructions, criteria}); the response's " +
			"`answers` map has one entry per question key, each carrying a `confidence` " +
			"(choice/score only) alongside the decided value. WHEN and HOW to use this " +
			"tool as part of your own judgment step is defined in your own agent " +
			"instructions file, not here -- read that, not this description.",
		promptSnippet: "Send a state + typed questions to the Jev Decisions API for a calibrated answer",
		promptGuidelines: [
			"Use jev_decide for the decision step your own agent instructions describe -- " +
				"this tool only documents the wire protocol; the judgment rules (what counts " +
				"as a valid candidate, what confidence threshold to require, etc) live in " +
				"your own instructions file. Follow that, not any summary of it here.",
		],
		parameters: Type.Object({
			state: Type.Union([Type.String(), Type.Record(Type.String(), Type.Unknown())], {
				description:
					"The content being evaluated -- either a plain string or a JSON object " +
					"(e.g. OCR'd text lines from a photo).",
			}),
			questions: Type.Record(Type.String(), Type.Unknown(), {
				description:
					"Dict of question-key -> question spec, passed through to the Decisions " +
					"API unmodified. See a question-set builder (e.g. QUESTION_SET_AGENT1 in " +
					"tools/jev_questions.py) for the exact shapes in use in this pipeline.",
			}),
		}),
		async execute(_toolCallId, params, signal) {
			// Never read JEV_MODEL etc into a variable that gets logged or echoed --
			// only the model slug (not the API key) is pipeline config, so this one
			// is safe to read here at call time.
			const model = process.env.JEV_MODEL || DEFAULT_MODEL;
			try {
				const response = await callDecisions(model, params.state, params.questions, { signal });
				return {
					content: [
						{
							type: "text",
							text: JSON.stringify(response, null, 2),
						},
					],
					details: response as Record<string, unknown>,
				};
			} catch (err) {
				// Clear, status-specific text for the calling agent -- 401/402 are
				// operator-fixable problems, not judgment calls the agent can retry around.
				if (err instanceof JevAuthError) {
					return {
						content: [{ type: "text", text: `jev_decide auth error: ${(err as Error).message}` }],
						isError: true,
					};
				}
				if (err instanceof JevPaymentError) {
					return {
						content: [{ type: "text", text: `jev_decide payment error: ${(err as Error).message}` }],
						isError: true,
					};
				}
				return {
					content: [{ type: "text", text: `jev_decide failed: ${(err as Error).message}` }],
					isError: true,
				};
			}
		},
	});
}
