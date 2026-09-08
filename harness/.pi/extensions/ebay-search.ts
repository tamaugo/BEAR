/**
 * eBay Browse API tools for Agent 2 (ebay-lookup).
 *
 * Ports the already-validated logic from ../../ebay_browse_lookup.py (tested live
 * against real eBay.co.uk data 2026-09-02, see agent2_instructionsv3.md's changelog
 * in agents/ at the repo root for results).
 *
 * Credentials: reads EBAY_APP_ID / EBAY_CERT_ID from process.env at call time.
 * Never hardcode these here — set them in your own shell before launching `pi`.
 * Dev ID is not needed; the Browse API's client-credentials grant only uses
 * App ID + Cert ID.
 *
 * getRateLimits is a STUBBED fixed-threshold check for tonight, not a real call
 * to eBay's Analytics API — see ebay_browse_lookup.py's own docstring for why
 * (no verified request shape for getUserRateLimits yet). Build it properly in
 * Step 6 of the plan before running large real batches.
 */

import { Type } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token";
const SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search";
const MARKETPLACE_ID = "EBAY_GB";
const SCOPE = "https://api.ebay.com/oauth/api_scope";

interface CachedToken {
	token: string;
	expiresAt: number; // epoch ms
}

interface EbayItemSummary {
	// eBay's listing id. Used to deduplicate the merged results of the two
	// searches issued per part number (see execute() below).
	itemId?: string;
	title?: string;
	price?: { value?: string; currency?: string };
	condition?: string;
	seller?: { username?: string };
	itemWebUrl?: string;
	// Everything below arrives only with fieldgroups=EXTENDED, and even then
	// not on every listing. These declarations are a hint about the shape we
	// hope for, NOT a guarantee — the payload is unvalidated JSON from eBay, so
	// every read below re-checks the type at runtime instead of trusting this.
	shortDescription?: string;
	mpn?: string;
	subtitle?: string;
	localizedAspects?: Array<{ type?: string; name?: string; value?: string }>;
	image?: { imageUrl?: string };
	thumbnailImages?: Array<{ imageUrl?: string }>;
}

function normalize(s: string): string {
	return s.replace(/[\s-]/g, "").toUpperCase();
}

/** A non-empty string, or null. Anything else (number, null, object) is null. */
function asNonEmptyString(value: unknown): string | null {
	return typeof value === "string" && value.length > 0 ? value : null;
}

/**
 * Every string on a search result that could plausibly carry the part number:
 * the title, plus whatever fieldgroups=EXTENDED attached.
 *
 * Deliberately defensive. EXTENDED's payload is not uniform — which extra
 * fields eBay sends varies by listing and by category, and any of them may be
 * absent or an unexpected shape. A single malformed listing must never throw
 * and kill a whole job, so this reads what is there and silently skips what
 * isn't. Mirrors extract_match_text() in ../../ebay_browse_lookup.py.
 */
function extractMatchText(item: EbayItemSummary): string[] {
	const chunks: string[] = [];
	const record = item as unknown as Record<string, unknown>;

	for (const key of ["title", "shortDescription", "mpn", "subtitle"]) {
		const value = asNonEmptyString(record[key]);
		if (value) chunks.push(value);
	}

	// Item specifics: a list of {type,name,value}. Take BOTH the name and the
	// value of every entry. Restricting to entries named exactly "MPN" would
	// miss the sellers who label the same field "Manufacturer Part Number",
	// "OE/OEM Part Number", "Reference OE/OEM Number" and so on — do not
	// "tidy" this into a name === "MPN" lookup.
	const aspects = record.localizedAspects;
	if (Array.isArray(aspects)) {
		for (const aspect of aspects) {
			if (typeof aspect !== "object" || aspect === null) continue;
			const aspectRecord = aspect as Record<string, unknown>;
			for (const key of ["name", "value"]) {
				const value = asNonEmptyString(aspectRecord[key]);
				if (value) chunks.push(value);
			}
		}
	}

	return chunks;
}

/**
 * Best available thumbnail URL for a listing, or null. image.imageUrl first,
 * then the first usable entry of thumbnailImages — either may be missing or
 * malformed. Mirrors extract_image_url() in ../../ebay_browse_lookup.py.
 */
function extractImageUrl(item: EbayItemSummary): string | null {
	const record = item as unknown as Record<string, unknown>;

	const image = record.image;
	if (typeof image === "object" && image !== null) {
		const url = asNonEmptyString((image as Record<string, unknown>).imageUrl);
		if (url) return url;
	}

	const thumbs = record.thumbnailImages;
	if (Array.isArray(thumbs)) {
		for (const thumb of thumbs) {
			if (typeof thumb !== "object" || thumb === null) continue;
			const url = asNonEmptyString((thumb as Record<string, unknown>).imageUrl);
			if (url) return url;
		}
	}

	return null;
}

/**
 * One Browse API search for one literal query string. Returns eBay's raw
 * itemSummaries array (possibly empty); merging, deduplication and the
 * exact-match post-filter are the caller's job. Mirrors _search_once() in
 * ../../ebay_browse_lookup.py.
 */
async function searchOnce(
	token: string,
	query: string,
	signal?: AbortSignal,
): Promise<EbayItemSummary[]> {
	const qs = new URLSearchParams({
		q: query,
		filter: "itemLocationCountry:GB",
		// 200, the Browse API per-page maximum — NOT 20. The exact-match test
		// in execute() is a POST-filter, so anything eBay doesn't return here
		// can never match. `q` is relevance-ranked keyword search, and a part
		// number built from generic-looking tokens ("C235 51 310") routinely
		// buries its genuine listings around position 25-60. This is free:
		// eBay's 5,000/day tier bills per CALL, not per result, so a
		// 200-result page costs exactly what a 20-result page did. Do not
		// "optimise" this back down.
		limit: "200",
		// Asks eBay for the extra per-item fields (shortDescription, mpn,
		// localizedAspects/item specifics) that extractMatchText reads.
		// Without it, a listing whose seller wrote a human-friendly title and
		// put the part number only in the MPN field can never match.
		fieldgroups: "EXTENDED",
	});

	const resp = await fetch(`${SEARCH_URL}?${qs.toString()}`, {
		headers: {
			Authorization: `Bearer ${token}`,
			"X-EBAY-C-MARKETPLACE-ID": MARKETPLACE_ID,
		},
		signal,
	});

	if (!resp.ok) {
		const errText = await resp.text();
		throw new Error(`eBay Browse API search failed (${resp.status}): ${errText}`);
	}

	const data = (await resp.json()) as { itemSummaries?: EbayItemSummary[] };
	return data.itemSummaries ?? [];
}

export default function (pi: ExtensionAPI) {
	let cachedToken: CachedToken | null = null;

	async function getAccessToken(signal?: AbortSignal): Promise<string> {
		const now = Date.now();
		if (cachedToken && cachedToken.expiresAt > now + 30_000) {
			return cachedToken.token;
		}

		// .trim() is deliberate: a trailing newline or space in an exported secret
		// (very easy to introduce when copy-pasting into `export EBAY_CERT_ID=...`)
		// reaches eBay as part of the credential and comes back as a 401
		// invalid_client, which reads like a wrong key rather than a stray byte.
		// The reference ebay_browse_lookup.py does NOT trim and has the same latent bug.
		const appId = process.env.EBAY_APP_ID?.trim();
		const certId = process.env.EBAY_CERT_ID?.trim();
		if (!appId || !certId) {
			throw new Error(
				"EBAY_APP_ID and/or EBAY_CERT_ID are not set in the environment. " +
					"Set them in your own shell before launching pi — this tool will " +
					"never read or accept them any other way.",
			);
		}

		const basicAuth = Buffer.from(`${appId}:${certId}`).toString("base64");
		const body = new URLSearchParams({
			grant_type: "client_credentials",
			scope: SCOPE,
		});

		const resp = await fetch(TOKEN_URL, {
			method: "POST",
			headers: {
				"Content-Type": "application/x-www-form-urlencoded",
				Authorization: `Basic ${basicAuth}`,
			},
			body: body.toString(),
			signal,
		});

		if (!resp.ok) {
			const errText = await resp.text();
			// Surface eBay's own error code verbatim — it distinguishes the causes,
			// which otherwise all look like "bad credentials".
			const isInvalidClient = errText.includes("invalid_client");
			throw new Error(
				`eBay OAuth token request failed (${resp.status}): ${errText}\n` +
					(isInvalidClient
						? "invalid_client means eBay rejected the App ID / Cert ID pair itself. " +
							"In likelihood order: (1) SANDBOX keys used against this PRODUCTION " +
							"endpoint — a production Cert ID starts 'PRD-', a sandbox one 'SBX-'; " +
							"(2) App ID and Cert ID mismatched, or the Dev ID pasted in place of " +
							"the Cert ID (the Browse API needs App ID + Cert ID only); " +
							"(3) the production keyset still shows 'disabled' on the Application " +
							"Keys page — the account-deletion-notification exemption must be " +
							"applied before ANY production call succeeds, including this one; " +
							"(4) a stray space or newline inside the exported value — this tool " +
							"now trims both, so this cause is handled."
						: "Check EBAY_APP_ID/EBAY_CERT_ID and that the production keyset is enabled."),
			);
		}

		const data = (await resp.json()) as { access_token: string; expires_in: number };
		cachedToken = {
			token: data.access_token,
			expiresAt: now + data.expires_in * 1000,
		};
		return cachedToken.token;
	}

	pi.registerTool({
		name: "ebay_search",
		label: "eBay Search",
		description:
			"Search eBay.co.uk for ACTIVE listings matching an exact car part number. " +
			"UK item location only. Scans up to 200 results and keeps every one whose " +
			"title OR eBay item-specifics (MPN and similar) contain the exact number, " +
			"returning each as: title | price currency | condition | seller | listing URL " +
			"(final field, copy it verbatim). Resolve them by following the Resolve section " +
			"of your own instructions — do not work from any summary of it. " +
			"Does NOT search sold/completed " +
			"listings — that data source isn't connected yet. Returns no candidates if " +
			"nothing matches exactly.",
		promptSnippet: "Search eBay.co.uk active listings for an exact part number, UK only",
		promptGuidelines: [
			"Use ebay_search with the primary part number only — never the OEM bonus number, never a modified/fuzzed version of the number.",
			"ebay_search already filters to UK item location and post-filters to exact part-number matches across each listing's title AND eBay's structured item specifics — do not re-filter or second-guess its exact-match results, but DO resolve the candidates yourself, following the Resolve section of your own instructions rather than any summary of it.",
		],
		parameters: Type.Object({
			part_number: Type.String({
				description: "The exact OEM part number to search for, as given by Agent 1 (primary number only, no OEM bonus).",
			}),
		}),
		async execute(_toolCallId, params, signal) {
			const token = await getAccessToken(signal);

			// TWO SEARCHES PER PART NUMBER, ON PURPOSE — do not "optimise" the
			// second one away.
			//
			// The exact-match filter below normalises both sides (strips spaces
			// and hyphens, uppercases), so it does not care how the part number
			// is punctuated. The SEARCH does. `q` is sent to eBay verbatim and
			// eBay's keyword tokeniser splits "DF71-67-5RZ" differently from
			// "DF71-675RZ", returning a different result set for each — so the
			// filter only ever sees what that one tokenisation happened to
			// return.
			//
			// Real case: the same photo of the same part was read by the vision
			// agent as "DF71-675RZ" on 7 Sep (found the listing, £12.00) and
			// "DF71-67-5RZ" on 8 Sep ("No eBay Listing Found"). The correct
			// listing was never in the second day's results at all. The upstream
			// vision agent's punctuation is not stable between runs, so the
			// search is made resilient to that variance here rather than
			// depending on curing it upstream.
			//
			// COST: this doubles the eBay calls for any part number that has
			// something to strip — a 20-40 part job goes from ~40 to ~80 calls
			// against the free tier's 5,000/day, which is comfortably fine. When
			// the raw and normalised strings are identical (e.g. "5WK43826")
			// only ONE call is made.
			const rawQuery = params.part_number;
			const normalisedQuery = normalize(rawQuery);
			const queries =
				normalisedQuery === rawQuery ? [rawQuery] : [rawQuery, normalisedQuery];

			// Merge, preserving order: everything the raw query returned, in
			// eBay's own relevance order, then only the extra listings the
			// normalised query turned up. Deduplicated on eBay's itemId so a
			// listing both queries returned is offered once. Not re-sorted.
			const allItems: EbayItemSummary[] = [];
			const seenItemIds = new Set<string>();
			for (const query of queries) {
				const items = await searchOnce(token, query, signal);
				for (const item of items) {
					// eBay's payload is unvalidated JSON; a null/garbage entry
					// must be skipped, not allowed to throw and kill the job.
					if (typeof item !== "object" || item === null) continue;
					const itemId = asNonEmptyString(
						(item as unknown as Record<string, unknown>).itemId,
					);
					// No usable itemId means we cannot prove it is a duplicate,
					// so keep it — the exact-match filter still has to pass it.
					if (itemId !== null) {
						if (seenItemIds.has(itemId)) continue;
						seenItemIds.add(itemId);
					}
					allItems.push(item);
				}
			}

			// Haystack = title PLUS the structured fields from fieldgroups=EXTENDED.
			// normalize() (strip spaces/hyphens, uppercase) is applied to both sides
			// so "C235 51 310" still matches a listing written "C23551310".
			const needle = normalize(params.part_number);
			const exact = allItems.filter((item) => {
				if (typeof item !== "object" || item === null) return false;
				return normalize(extractMatchText(item).join(" ")).includes(needle);
			});

			if (exact.length === 0) {
				const note =
					allItems.length > 0
						? ` (${allItems.length} loosely-matching result(s) came back from the keyword search, but none contained the exact part number in the title or item specifics — not used, per exact-match-only rule)`
						: "";
				return {
					content: [
						{
							type: "text",
							text: `No exact-match active UK listing found for "${params.part_number}".${note}`,
						},
					],
					details: { part_number: params.part_number, matchCount: 0 },
				};
			}

			// LINE FORMAT IS A CONTRACT. Agent 2 v5 reads these as pipe-delimited
			// text and copies the FINAL field through as the listing URL, verbatim.
			// Do not append, reorder or remove fields here without updating
			// agents/agent2_instructionsv5.md and .pi/agents/agent2-ebay-lookup.md
			// in the same change — the thumbnail deliberately does NOT go on this
			// line for exactly that reason (it rides in `details` instead).
			const lines = exact.map((item) => {
				const price = item.price?.value ?? "?";
				const currency = item.price?.currency ?? "";
				const seller = item.seller?.username ?? "unknown";
				const condition = item.condition ?? "";
				return `- "${item.title}" | ${price} ${currency} | ${condition} | seller: ${seller} | ${item.itemWebUrl ?? ""}`;
			});

			// Structured mirror of the same candidates, carrying the thumbnail URL
			// that has no safe home on the prompt-facing line above. Available to
			// the harness/UI and to any later consumer that wants images, without
			// touching what Agent 2 parses.
			const candidates = exact.map((item) => ({
				title: item.title ?? null,
				price: item.price?.value ?? null,
				currency: item.price?.currency ?? null,
				condition: item.condition ?? null,
				seller: item.seller?.username ?? null,
				url: item.itemWebUrl ?? null,
				image: extractImageUrl(item),
			}));

			return {
				content: [
					{
						type: "text",
						text:
							`${exact.length} exact-match ACTIVE UK listing(s) for "${params.part_number}" ` +
							`(no sold-price data available):\n${lines.join("\n")}`,
					},
				],
				details: { part_number: params.part_number, matchCount: exact.length, candidates },
			};
		},
	});

	pi.registerTool({
		name: "getRateLimits",
		label: "eBay Rate Limit Check (stub)",
		description:
			"STUBBED for now — does not call eBay's real Analytics API. Always reports quota " +
			"as sufficient. Real implementation is deferred to a later pass (Step 6 of the " +
			"project plan); safe to leave stubbed for small test batches only, not for a " +
			"large real job.",
		promptSnippet: "Check eBay API rate limits before starting a job (currently stubbed)",
		parameters: Type.Object({
			expectedCalls: Type.Optional(
				Type.Number({ description: "Approximate number of eBay calls expected for this job" }),
			),
		}),
		async execute() {
			return {
				content: [
					{
						type: "text",
						text:
							"[STUB] Rate limit check not yet implemented against eBay's real Analytics " +
							"API — assuming quota is sufficient and proceeding. Do not rely on this for " +
							"a large real batch until it's built for real.",
					},
				],
				details: { stubbed: true },
			};
		},
	});
}
