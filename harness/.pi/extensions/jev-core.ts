/**
 * Zero-dependency core for TypeSafe Jev (OpenRouter's Decisions API): request
 * building, .env/API-key resolution, the retrying HTTP call, and response
 * parsing. Imports NOTHING but node builtins, specifically so this file can be
 * loaded outside pi's extension host -- e.g. by tests/test_jev_decisions.mjs,
 * which needs the real fetch-calling logic without pulling in
 * @earendil-works/pi-ai or @earendil-works/pi-coding-agent.
 *
 * pi-specific wiring (the `jev_decide` tool registration, Type schemas,
 * ExtensionAPI) lives in ./jev-decisions.ts, which imports these helpers.
 *
 * TypeScript port of ../../../tools/jev_client.py -- same endpoint, same retry and
 * error semantics (401/402 fail fast, 429/5xx retry 3x with 1s/2s/4s backoff), same
 * .env fallback precedence (real env var wins, .env is a local-run convenience only,
 * never written back into process.env so its origin stays visible to anyone
 * inspecting the environment). See that file's docstring for how the request/
 * response shape was confirmed against OpenRouter's OpenAPI spec.
 */

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions";
export const DEFAULT_MODEL = "typesafe/jev-1.13";

// 429/5xx are treated as transient; retry with exponential backoff (1s, 2s, 4s).
const MAX_ATTEMPTS = 3;
const BACKOFF_BASE_MS = 1000;

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Three levels up: extensions/ -> .pi/ -> harness/ -> repo root. Matches
// tools/jev_client.py's REPO_ROOT (one level up from tools/, i.e. also repo root) --
// both land on the same BEAR/.env.
const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");
const ENV_FILE = path.join(REPO_ROOT, ".env");

/** The Decisions API returned an error we can't recover from by retrying. */
export class JevAPIError extends Error {}
/** 401 -- the API key is missing, wrong, or revoked. Retrying won't help. */
export class JevAuthError extends JevAPIError {}
/** 402 -- the OpenRouter account is out of credits. Retrying won't help. */
export class JevPaymentError extends JevAPIError {}

/** strip() equivalent for a fixed set of characters, applied to both ends only. */
function stripChars(value: string, chars: string): string {
	let start = 0;
	let end = value.length;
	while (start < end && chars.includes(value[start])) start++;
	while (end > start && chars.includes(value[end - 1])) end--;
	return value.slice(start, end);
}

/**
 * Minimal KEY=VALUE .env parser -- mirrors tools/jev_client.py's _parse_dotenv().
 * Deliberately dumb: one assignment per line, '#' starts a comment, surrounding
 * quotes are stripped. Good enough for the handful of vars in .env.example.
 */
export function parseEnvFile(text: string): Record<string, string> {
	const values: Record<string, string> = {};
	for (const rawLine of text.split("\n")) {
		const line = rawLine.trim();
		if (!line || line.startsWith("#") || !line.includes("=")) continue;
		const eq = line.indexOf("=");
		const key = line.slice(0, eq).trim();
		let value = line.slice(eq + 1).trim();
		// Python does .strip('"').strip("'") in that order -- mirror it exactly
		// rather than stripping both quote characters in one pass.
		value = stripChars(value, '"');
		value = stripChars(value, "'");
		if (key) values[key] = value;
	}
	return values;
}

/** Where a resolved API key came from -- surfaced in 401 errors so a bad key is easy to trace. */
export type ApiKeySource = "shell environment (overrides .env)" | `.env file at ${string}`;

export interface ResolvedApiKey {
	key: string;
	source: ApiKeySource;
}

/**
 * Real shell env wins; .env is just a fallback for local runs -- never mutate
 * process.env with it, so the key's origin stays visible to anyone inspecting env.
 * Same precedence as resolveApiKey(), but also reports which of the two it used --
 * needed to build a self-diagnosing 401 message (see callDecisions below).
 */
export function resolveApiKeyDetailed(env: NodeJS.ProcessEnv = process.env): ResolvedApiKey {
	const envKey = env.OPENROUTER_API_KEY;
	if (envKey) return { key: envKey, source: "shell environment (overrides .env)" };
	if (existsSync(ENV_FILE)) {
		const fileKey = parseEnvFile(readFileSync(ENV_FILE, "utf-8")).OPENROUTER_API_KEY;
		if (fileKey) return { key: fileKey, source: `.env file at ${ENV_FILE}` };
	}
	throw new Error(
		"OPENROUTER_API_KEY not found in the environment or in .env at " +
			`${ENV_FILE}. Copy .env.example to .env and fill it in, or export the ` +
			"variable in your shell.",
	);
}

/** Back-compat wrapper -- jev-decisions.ts and tests only need the key string. */
export function resolveApiKey(env: NodeJS.ProcessEnv = process.env): string {
	return resolveApiKeyDetailed(env).key;
}

/**
 * Builds the checklist appended to a 401 JevAuthError. Never includes more than the
 * first 7 characters of the key -- enough to eyeball "is this the .env.example
 * placeholder" without logging anything a real secret manager would care about.
 */
function describeKeyForAuthError(apiKey: string, source: string): string {
	const preview = apiKey.slice(0, 7);
	const isPlaceholder = /^sk-or-\.\.\.$/.test(apiKey) || apiKey.length < 20;
	return (
		`The key used came from ${source} (starts "${preview}", ${apiKey.length} chars). ` +
		(isPlaceholder
			? `That looks like the .env.example PLACEHOLDER, not a real key: copy your real ` +
				`key into ${ENV_FILE}. `
			: `If that starts with "sk-or-..." or "sk-or-v1" followed by three dots it is the ` +
				`.env.example PLACEHOLDER, not a real key: copy your real key into ${ENV_FILE}. ` +
				`If it is a real-looking key, it may be stale/revoked: regenerate at ` +
				`openrouter.ai/settings/keys. `) +
		"NOTE: a shell export of OPENROUTER_API_KEY overrides the .env file -- check: " +
		'echo ${OPENROUTER_API_KEY:+SET (shadows .env)}'
	);
}

export interface DecisionsRequest {
	url: string;
	method: "POST";
	headers: Record<string, string>;
	body: string;
}

/** Pure request builder -- no I/O, so it's testable without a live API key. */
export function buildRequest(
	model: string,
	state: unknown,
	questions: Record<string, unknown>,
	apiKey: string,
): DecisionsRequest {
	return {
		url: DECISIONS_URL,
		method: "POST",
		headers: {
			Authorization: `Bearer ${apiKey}`,
			"Content-Type": "application/json",
		},
		body: JSON.stringify({ model, state, questions }),
	};
}

/**
 * Decisions error bodies are {"error": {"code": int, "message": str}}; fall back
 * to raw text if the provider ever returns something else on a 5xx.
 */
export function errorMessage(bodyText: string, status: number): string {
	try {
		const payload = JSON.parse(bodyText) as { error?: { message?: string } };
		if (payload?.error?.message) return payload.error.message;
	} catch {
		// not JSON -- fall through to raw text below
	}
	return bodyText.slice(0, 500) || `HTTP ${status}`;
}

function sleep(ms: number): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * POST one Decisions request and return the parsed JSON response. `state` is the
 * content being evaluated (string, object, or array); `questions` is a dict of
 * question-key -> question spec (see tools/jev_questions.py for the shapes BEAR
 * uses; this client passes whatever it is given straight through unmodified).
 */
export async function callDecisions(
	model: string,
	state: unknown,
	questions: Record<string, unknown>,
	options: { apiKey?: string; timeoutMs?: number; maxAttempts?: number; signal?: AbortSignal } = {},
): Promise<unknown> {
	// Track where the key came from (not just its value) so a 401 can name the
	// exact place to fix -- caller-supplied keys have no .env/shell provenance to report.
	let apiKey: string;
	let keySource: string;
	if (options.apiKey) {
		apiKey = options.apiKey;
		keySource = "an explicit apiKey option (not resolved from .env or the shell)";
	} else {
		const resolved = resolveApiKeyDetailed();
		apiKey = resolved.key;
		keySource = resolved.source;
	}
	const maxAttempts = options.maxAttempts ?? MAX_ATTEMPTS;
	const timeoutMs = options.timeoutMs ?? 60_000;
	const request = buildRequest(model, state, questions, apiKey);

	let lastError: Error | null = null;
	for (let attempt = 1; attempt <= maxAttempts; attempt++) {
		const timeoutController = new AbortController();
		const timeoutId = setTimeout(() => timeoutController.abort(), timeoutMs);
		// Abort if either the caller's own signal fires or our timeout does.
		const onCallerAbort = () => timeoutController.abort();
		options.signal?.addEventListener("abort", onCallerAbort);

		try {
			const response = await fetch(request.url, {
				method: request.method,
				headers: request.headers,
				body: request.body,
				signal: timeoutController.signal,
			});

			if (response.ok) {
				return await response.json();
			}

			const bodyText = await response.text();
			const message = errorMessage(bodyText, response.status);

			if (response.status === 401) {
				throw new JevAuthError(
					`Decisions API rejected the API key (401): ${message}. ` +
						describeKeyForAuthError(apiKey, keySource),
				);
			}
			if (response.status === 402) {
				throw new JevPaymentError(`OpenRouter account is out of credits (402): ${message}`);
			}
			if (response.status === 429 || response.status >= 500) {
				lastError = new JevAPIError(`Decisions API returned ${response.status}: ${message}`);
				if (attempt < maxAttempts) {
					await sleep(BACKOFF_BASE_MS * 2 ** (attempt - 1));
					continue;
				}
				throw lastError;
			}
			// Other 4xx codes (400/403/404/413) mean the request itself is wrong --
			// retrying an unchanged request would just fail the same way again.
			throw new JevAPIError(`Decisions API returned ${response.status}: ${message}`);
		} catch (err) {
			if (err instanceof JevAPIError) throw err;
			// Network error, abort, or non-HTTP fetch failure.
			lastError = new JevAPIError(`Network error contacting Decisions API: ${(err as Error).message}`);
			if (attempt < maxAttempts) {
				await sleep(BACKOFF_BASE_MS * 2 ** (attempt - 1));
				continue;
			}
			throw lastError;
		} finally {
			clearTimeout(timeoutId);
			options.signal?.removeEventListener("abort", onCallerAbort);
		}
	}

	throw lastError ?? new JevAPIError("unreachable: retry loop exited without returning or throwing");
}

// --- response helpers ------------------------------------------------------------
// Answer shape depends on the question's `type`: noul -> {"noul": float}, choice ->
// {"choice": str, "confidence": float, "probabilities": {...}}, score -> {"score":
// float, "confidence": float, "legend": {...}, "probabilities": {...}}.

/** The full answers map plus usage.cost, pulled out of a raw Decisions response. */
export function extractAnswers(response: unknown): {
	answers: Record<string, unknown>;
	cost: number | null;
} {
	const record = (response ?? {}) as Record<string, unknown>;
	const answers = (record.answers ?? {}) as Record<string, unknown>;
	const usage = record.usage as { cost?: number } | undefined;
	const cost = typeof usage?.cost === "number" ? usage.cost : null;
	return { answers, cost };
}
