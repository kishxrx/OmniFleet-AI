# Control Wiring & QA Matrix

This document is the control-by-control companion to the [Operator Guide](OPERATOR_GUIDE.md). It records what each visible interactive control is supposed to do and how the browser acceptance suite exercises it.

**Important:** A control can only operate the software simulation. No button sends a command to a physical drone, camera, radio, autopilot or flight controller.

## Global controls and navigation

| Control | Expected behavior | Verification |
|---|---|---|
| Sidebar: Command overview | Scrolls to the overview section | Browser anchor-target check |
| Sidebar: Mission control | Scrolls to Mission Control | Browser anchor-target check |
| Sidebar: Fleet assets | Scrolls to Fleet Assets | Browser anchor-target check |
| Sidebar: Swarm network | Scrolls to Swarm Communications | Browser anchor-target check |
| Sidebar: Activity & logs | Scrolls to Operations Activity | Browser anchor-target check |
| `?` Help | Opens the operator quick-reference dialog | Open, close, Escape and section-jump checks |
| Refresh | Reloads dashboard state from the API | Browser click and API response check |
| Reset (`↻`) | Shows a confirmation prompt, then restores seeded demo state | Accept-confirmation and three-vehicle state check |

## Operational map and mission tasking

| Control | Expected behavior | Verification |
|---|---|---|
| Fit map (`⤢`) | Fits the theatre or confirms full-theatre view in schematic fallback | Browser click; fallback status asserted |
| Routes, Zones, Labels | Toggle the corresponding map overlays | Each overlay toggled off and on |
| Sensor rings, Comm range | Toggle illustrative sensor and nominal communication circles | Each overlay toggled off and on |
| Test objects, Observations | Toggle virtual objects and observation overlays | Each overlay toggled off and on |
| Vehicle selector | Chooses which vehicle receives a map waypoint | Select Scout-1, then create a proposal |
| Place waypoint | Enters map-tasking mode; next valid map click creates a pending proposal | Map click, pending-state assertion, reject action |
| Place test object | Enters virtual-object placement mode | Clicked and checked for active placement status |
| Draw area | Starts polygon drawing on the map | Browser drawing sequence |
| Generate sectors | Submits a drawn polygon and selected lane spacing | Valid polygon, spacing change and proposal assertion |
| Clear | Cancels/clears the in-progress polygon and disables Generate sectors | Clicked during an incomplete polygon; state asserted |

## Mission Control and recovery

| Control | Expected behavior | Verification |
|---|---|---|
| Three prompt examples | Populate the mission instruction box | All three buttons clicked and exact text compared |
| Generate plan | Creates a proposal, not immediate execution | Pending proposal asserted |
| Approve & execute | Revalidates and starts the simulation mission | Execution state asserted after click |
| Reject proposal | Rejects a pending proposal | Rejected state asserted for map and coverage proposals |
| Inject vehicle outage | Marks selected asset unavailable and may create a recovery proposal | Scout-1 outage injected; second proposal asserted |
| Approve recovery | Approves the recovery proposal separately | Recovery enters execution only after second approval |

## Sensor Intelligence and virtual objects

| Control | Expected behavior | Verification |
|---|---|---|
| Object label | Supplies the virtual object's label | Filled in browser test |
| Category selector | Selects marker/vehicle/person/structure/other category | Category changed in browser test |
| Difficulty selector | Selects Easy/Medium/Hard synthetic detection difficulty | Easy selected in browser test |
| Visible checkbox | Controls whether future simulated scans can observe the object | Checked state submitted; backend hidden/show behavior tested |
| Place on map / Place test object | Starts map placement using current object form values | Both placement buttons clicked; object creation asserted |
| Scan now | Runs a synthetic scan for currently visible objects | Clicked; backend scan endpoint and observation update asserted |
| Move | Arms map placement for an existing object | Move click followed by map click; position update asserted |
| Hide / Show | Changes visibility for future observations | Both states toggled in browser and API tests |
| Remove | Removes active object from map state while retaining past event history | Clicked; object row disappears; backend history test passes |
| Sensor enabled | Enables/disables new simulated observations per vehicle | Switch toggled both ways |
| Sensor range | Updates illustrative sensor footprint and scan radius | Slider changed and backend update confirmed |
| Comm range | Updates the displayed nominal communication radius | Slider changed and backend update confirmed |

## Blackbox Analytics

| Control | Expected behavior | Verification |
|---|---|---|
| Vehicle selector | Selects which asset's telemetry is shown | Changed to Scout-2; data refreshed |
| Refresh data | Retrieves current bounded telemetry and events | Clicked; slider becomes enabled after samples exist |
| Replay slider | Selects a telemetry sample and moves replay marker | Slider moved and input event dispatched |
| Show sample on map | Displays the selected sample's position on the operational map | Clicked in browser suite |
| Play replay / Pause replay | Advances sample selection, then stops playback | Play and pause both clicked |

## Swarm Intelligence & Communications

| Control | Expected behavior | Verification |
|---|---|---|
| Swarm communications | Globally enables/pauses simulated message delivery | Switch toggled off and on |
| Coordination mode | Selects centralized or hybrid simulated routing | Both modes selected and applied |
| Peer mesh | Enables/disables direct peer routing in hybrid mode | Switch toggled and policy applied |
| Coordinator link | Models central operator/coordinator connectivity | Switch changed and policy applied |
| Apply network policy | Persists the selected network configuration | Clicked; persisted status note asserted |
| Scan route conflicts | Runs destination-proximity heuristic and reports potential conflicts | Clicked and API endpoint exercised |
| Per-vehicle radios | Enables/disables an individual vehicle's simulated radio | Scout-2 radio toggled both ways |
| Request fleet status | Sends a status request and collects reachable reports | Clicked; backend message workflow tested |
| Test peer link | Sends a peer test from selected sender to recipient | Sender/recipient selected; button clicked; acknowledgment path exercised |
| Broadcast recipient | Selects all connected vehicles or an individual vehicle | Individual recipient selected |
| Broadcast text | Supplies an informational, non-executable message | Text entered and broadcast button clicked |
| Broadcast to fleet | Publishes the informational message | Clicked; backend delivery result checked |
| Detection source | Selects the reporting vehicle | Scout-1 selected |
| Detection label and X/Y/confidence | Supply a structured synthetic detection | All fields populated; proposal response checked |
| Broadcast detection & request inspection | Shares a synthetic detection and may create a pending inspection proposal | Clicked; pending proposal asserted |

## Automated wiring coverage

The Chromium acceptance script (`tools/browser_acceptance.py`) runs the actual shipped HTML, CSS and JavaScript. It covers **13 interaction groups**, including all seven map layers, all prompt presets, all primary map and coverage actions, virtual object CRUD, sensor settings, blackbox playback, swarm settings and messaging, mission/recovery approval, reset confirmation, help navigation and a 390-pixel mobile overflow check.

The browser uses an in-process bridge to FastAPI's real application endpoints because this verification environment blocks Chromium's direct localhost TCP access. This is not a mocked backend. A separate live Uvicorn smoke pass was also run against the actual TCP server.

For the latest counts and exact test limitations, see [Testing & Verification](TESTING_AND_VERIFICATION.md).

## Deliberately display-only elements

These UI elements are not buttons or active workflows in v0.9.2 and are presented as status/roadmap chrome rather than working controls:

- **Northstar Ops workspace badge:** this build contains one local demo workspace; there is no workspace switcher.
- **Agent orchestration** and **Analytics** under the muted System navigation label: roadmap placeholders, not active destinations. Agent activity is visible in the current dashboard.
- **Latest events** label above Operations Activity: a static heading, not a filter menu.
- The live clock, fleet/agent/status cards, map legends and metric cards are read-only displays.

The actionable controls listed above are wired and covered by the interaction tests. These display-only elements are intentionally not counted as buttons.
