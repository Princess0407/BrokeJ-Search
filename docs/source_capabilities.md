# Discovery source capabilities

Research date: 2026-11-11
Scope: Milestone 2 discovery only

## Status language

- **Implemented (fixture-tested)** means a connector exists and passes deterministic mocked-response tests. It does not claim a live-provider smoke test.
- **Deferred** means no connector will be shipped in this milestone.
- **Manual/official integration only** means the system may accept a user-provided listing URL/file or an approved API later, but will not scrape the site.
- A source becomes **implemented** in the README only after its connector and fixture tests exist and pass.

## Capability matrix

| Source | Public/official interface | Auth | Pagination/incremental behavior | Useful data | Constraints and reliability | Phase decision |
| --- | --- | --- | --- | --- | --- | --- |
| Greenhouse Job Board | Documented public GET API: `boards-api.greenhouse.io/v1/boards/{token}/jobs` | None for GET | List endpoint documents no cursor; response/item hashes and HTTP validators when present prevent reprocessing | Posting/internal IDs, title, location, updated time, URL, description, departments/offices; per-job endpoint may expose first published, deadline, metadata, and pay ranges | Board token must be configured. Public fields vary by employer. No published GET rate limit found; apply a conservative configurable rate and handle 429 | **Implemented (fixture-tested)** |
| Lever Postings | Documented public Postings API: `api.lever.co/v0/postings/{site}` (plus EU base) | None for published GET listings | `skip`/`limit` pagination; no documented updated-since cursor, so hash unchanged postings | Posting ID, title, hosted/apply URLs, description/list content, location, commitment, team, department | Site name and region must be configured. Published listings only. No full-text search. Public GET limit is not documented; throttle and handle 429 | **Implemented (fixture-tested)** |
| Ashby public job board | Documented public GET API: `api.ashbyhq.com/posting-api/job-board/{name}` | None | Full current board response; no public cursor. Hash response/items. Authenticated employer API has pagination/sync tokens but is not assumed available | Title, locations, remote/workplace type, descriptions, published time, employment type, URLs, and optional structured compensation | Board name must be configured. Public response does not document a separate job ID; derive the stable source identity from the job URL and retain it visibly | **Implemented (fixture-tested)** |
| Company career pages | Varies: official ATS API, JSON feed, RSS, or employer API | Varies | Varies | Potentially authoritative | No generic HTML scraper. Add a connector only after documenting permission, schema, robots policy where applicable, and fixtures | **Deferred**, except companies using the selected ATS connectors |
| Wellfound | No permitted discovery API identified for this use | Account/site dependent | Not applicable | Startup jobs | Wellfound terms prohibit automated or non-automated harvesting/scraping except where expressly permitted | **Manual/official integration only** |
| YC Work at a Startup | Public job pages; no documented public discovery API identified in this review | Some workflows use an account | Web pagination/filtering is not an API contract | Startup/company/job data | Public visibility is not permission to automate collection. Revisit only with a documented feed/API or written permission | **Deferred**; accept user-provided URLs later |
| Indeed | Partner documentation and provisioned integrations; documented Job Sync APIs primarily create/manage publisher or ATS jobs rather than provide general job-seeker search | OAuth/partner provisioning | Product-specific | Job posting and partner integration data | Do not scrape search results. A partner-approved discovery product must be evaluated separately | **Manual/official integration only** |
| LinkedIn | Partner Talent APIs for posting/managing jobs; no generally available job-search discovery API identified in this review | OAuth plus approved product access | Product-specific | Partner posting workflows | Do not scrape listings, bypass authentication, or automate consumer search pages | **Manual/official integration only** |
| X/Twitter | Official API access is authenticated and plan/rate-limit dependent | Required | API-specific cursors | Public posts, not verified vacancies | A post is a lead. Store original link and never promote it to a confirmed vacancy without an official listing. No connector until credentials and terms are approved | **Deferred optional lead connector** |
| Public RSS/community boards | Feed or API must be documented per source | Usually none | Feed timestamps/IDs | Public hiring leads/listings | Each feed needs its own permission note, identity rules, fixtures, and lead-vs-listing classification | **Deferred extension point** |
| Manual import | User-provided URL or JSON/CSV file | User supplies accessible content | Import checksum | Any schema the importer explicitly maps | Must retain original source and mark unverified fields. This is not a license to fetch protected URLs | **Deferred until after initial connectors** |

## Primary references

- [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html) documents unauthenticated GET access to published job-board data, list and detail fields, and the `content=true` option.
- [Lever Postings API](https://github.com/lever/postings-api) documents public published postings, `skip`/`limit` pagination, global/EU instances, and the absence of full-text search.
- [Ashby public Job Postings API](https://developers.ashbyhq.com/docs/public-job-posting-api) documents the unauthenticated job-board endpoint, its current fields, workplace/employment enums, and optional compensation.
- [Ashby authenticated `job.list`](https://developers.ashbyhq.com/reference/joblist) documents cursor and sync-token support, but requires employer-side `jobsRead` permission and is not the public connector selected here.
- [Wellfound Talent General Terms](https://wellfound.com/terms) expressly restrict harvesting and scraping unless permitted.
- [Indeed Partner Documentation](https://docs.indeed.com/) describes provisioned partner APIs and publisher integrations; [Job Sync](https://docs.indeed.com/job-sync-api) is for creating/managing postings, not a general search feed.
- [LinkedIn Job Posting API](https://learn.microsoft.com/en-us/linkedin/talent/job-postings/api/create-jobs) documents an approved/authenticated posting integration, not a general job-discovery feed.
- [YC startup job pages](https://www.ycombinator.com/jobs/role/all) are publicly viewable, but no public discovery API contract was identified in this review.

Provider interfaces and terms can change. Revalidate the linked primary documentation before enabling a connector in production.

## Initial connector contracts

### Greenhouse

Configuration:

- `board_token` (required)
- company display name/website (required because list payloads may not supply both)
- minimum request interval and optional page/item cap

Fetch:

1. GET the jobs list with `content=true`.
2. Normalize each posting from the list response.
3. Fetch a per-job detail only when the common record needs a documented detail field absent from the list; this avoids unnecessary requests.
4. Use Greenhouse posting ID as source ID and keep `internal_job_id` as metadata.

The connector does not call application submission endpoints or retrieve application questions.

### Lever

Configuration:

- `site_name` (required)
- `region`: `global` or `eu`
- `page_size`, page cap, and minimum request interval

Fetch pages with `mode=json`, `skip`, and `limit` until a short/empty page or the configured safety cap. Normalize the posting ID, title, categories, description/list fields, hosted URL, apply URL, and source-created/updated values when supplied. Preserve all original JSON.

The connector never calls the application POST endpoint.

### Ashby

Configuration:

- `job_board_name` (required)
- `include_compensation`, default true
- minimum request interval and item cap

Fetch the documented public board endpoint. Ignore `isListed=false` records for normal discovery but retain aggregate counts in the source run. Use the normalized job URL (or apply URL if job URL is absent) as the source identity because the public contract does not document a separate job ID. Persist both URLs and all compensation components.

The connector does not use employer-authenticated endpoints.

## Rate limits and polite access

The public documentation reviewed does not state stable numeric GET limits for the three selected endpoints. Therefore:

- Default to at most one request per source per second, configurable downward.
- Keep concurrency across different sources small; never parallelize pages of the same source.
- Honor `Retry-After` and HTTP 429.
- Use conditional headers only when the provider returned validators.
- Cache response hashes and skip unchanged normalization/database writes.
- Set a descriptive user agent and finite timeouts.
- Stop on repeated schema errors rather than hammering an endpoint.

## Freshness and lifecycle limitations

Public ATS APIs are authoritative for what an employer currently publishes on that board, but they may not expose explicit closure history. Absence from one successful full-board response increments a missing count; it does not immediately expire the canonical job. Source-wide failures do not increment missing counts.

The initial connectors can report discovery and last-seen time reliably. Posting dates, deadlines, compensation, employment type, graduation restrictions, and work arrangement remain unknown when the provider does not state them.

## Adding another source

A source proposal must include, before code:

1. Primary documentation or written permission.
2. Authentication and secret handling.
3. Rate limits and retry guidance, or a conservative documented default.
4. Pagination and incremental semantics.
5. Stable source identity.
6. Field-origin mapping and raw snapshot policy.
7. Terms/robots constraints for HTML access.
8. Saved success, empty, malformed, rate-limited, and temporary-failure fixtures.
9. Clear classification as verified listing or unverified lead.

If any of permission, stable identity, or deterministic fixture coverage is missing, the source remains deferred.
