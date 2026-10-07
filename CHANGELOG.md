# BEAR version log

Newest first. The current version is in the `VERSION` file and shows in the top corner of the web page.

## 0.3

- **Model selection**: the web page has a *Model setup* drop-down. Pick one whole setup per run: *Default*, *Beta* or *Experimental*.
- **Increased cost savings**: the *Beta* setup uses OpenAI Luna Decisions for the photo check (Gemini stays as the backup), about 26% cheaper per job with the same results on the i40 test.
- **Experimental Claude Haiku 5.5**: the *Experimental* setup reads the photos with Claude Haiku 5.5. It is a test version (16-17 of 18 part numbers on the i40 test), so not for real jobs yet.

## 0.2

- Mac `bear` command and `bear ui` web page: read part numbers from photos, price them against live eBay UK listings, and write `results.xlsx`.
