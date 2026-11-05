# Design

## Workbench

Fixed desktop navigation, responsive top navigation, cached-inventory table and
coverage timeline beside run configuration. At narrower widths configuration
stacks below the data. Native Segoe UI/system fonts and tabular numerals; no
remote fonts or chart dependency. Palette: #F3F6FA / #FFFFFF / #18263B / #2856B6 /
#24715C / #A65D18, with accessible dark equivalents. Quiet borders, no card shadows.

Simulation has New simulation and History. Existing result/audit components are
reused. Data and Providers retain their APIs and functionality with shared tokens.
Data is lazy-mounted so entering Simulation does not query the full catalog.
Once visited, pages stay mounted to preserve ongoing work.

## Coverage and review

Read cache inventory and selected security details only. A shared deduplicated
queue caps detail requests at four, even when selections change. Invalidation
clears cached promises and rejects obsolete queued generations. Component cleanup
ignores late selection responses. Completed Data jobs, cache deletion, return from
Data and explicit refresh invalidate simulation coverage/review.

Common coverage uses the latest first and earliest last raw positive close across
selected securities plus benchmark; benchmark also needs a positive adjusted
close. Align to the benchmark grid and require two days. Interior gaps are not
removed from the grid. Initialize dates once; never overwrite manually chosen
dates. Explicit Use common range applies the current recommendation.

Request dates can extend beyond common coverage inside benchmark bounds. Weekend
boundaries are retained. Missing opens/held-close risks, financial eligibility by
visible filing date and unavailable earnings remain separate concerns. Mixed or
legacy price modes in the requested range, missing benchmark adjusted close,
fewer than two benchmark sessions and no stock prices block review. Missing saved
universe members remain visible and require preparation or explicit removal.

Review uses existing preflight. Parameters or data revision invalidate it. Warnings
require acknowledgement, including widened intervals. A synchronous ref lock
prevents duplicate submission. No inference before Confirm and run. Run submission
errors instruct users to check History before retrying (network ambiguity).
Polling never resubmits; explicit Retry status resumes polling after an error.

## Constraints

No independent exchange calendar: benchmark cache omissions cannot be detected.
Preflight is not a guarantee of successful future valuation. The existing paged
cache-list endpoint includes entries without prices; those are hidden by default
within each page, with an explicit toggle and pagination explanation. No silent
selection/detail truncation. Large selections can take time because the unchanged
detail endpoint returns full history; progress is displayed.
