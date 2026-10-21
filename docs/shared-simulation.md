# Shared simulation and recorded movement

## Data flow

`MatchEngine` chooses an intention (carry, pass, shot or restart). `MatchWorld` advances players and ball together: flights use steps of at most 50 ms, ordinary movement 100 ms and dead-ball settling 250 ms. Swept contacts resolve movement within each step. The match director emits pass and shot outcomes after the physical contact or boundary crossing resolves. `simulate_match` returns events and frames recorded from this same world. The older `TrackingBuilder` remains a compatibility helper; it is not used by the default generator.

Live matches use `stream_match`: a worker generates inputs progressively into a queue capped at 64 items. Paused or slower playback fills the queue and blocks generation. The worker retains only its latest frame; received history remains available in the match session for rewind and evidence. One clock instant is buffered to publish events before frames at that instant, including restart placement updates. Closing the stream stops and joins the worker. The offline CLI still computes and saves a complete fixture.

## Movement and contacts

- Role-based formation targets, a nearby presser, covering defender and receiver preparation drive movement.
- Player velocity changes are bounded by acceleration and top speed. Facing rotates toward travel or an intended kick; release waits for control and alignment, with a brief preparation phase.
- Controlled balls move toward the carrier's foot over time. Carries move the player and ball, rather than placing the ball at an authored endpoint.
- Ground passes decelerate. Lofted balls use gravity, lose energy on bounces and settle into rolling motion.
- Swept ball contacts use relative player movement. The earliest reachable player contact or pitch boundary wins, reducing tunnelling between steps. Height permits real aerial clearance.
- Solid player discs use swept relative movement and contact impulses, with iterative overlap repair and anticipatory steering. Teams share the same collision rules. A crowded solver step holds unresolved displacement instead of advancing through bodies.
- Restart takers and retreating players steer around the stationary ball. The contact solver allows longer contact chains to converge, preventing a blocked retreat from freezing a kickoff. A regression reproduces the crowded midfield position from balanced seed 29.
- Ball/body volumes include every player, including nonreceiving teammates and the kicker. Physical contact is separate from receiving/goalkeeper reach. Carries also check bodies; a teammate who actually receives a pass becomes its recorded receiver. A teammate can block a shot.
- A received pass, interception, outfield shot block, goalkeeper save or goal-line crossing determines the recorded outcome. Goalkeepers can catch reachable shots; this is a simplified reach model.
- Substitutions update the active bodies and introduce the replacement from the touchline. Half-time resets and explicit restart placements are marked discontinuities, not cross-pitch ball flights.

## Recording and playback

`TrackingFrame.interval_ms` describes time since the preceding recorded frame within the period. Regular frames remain at one-second boundaries, with additional kick and contact frames. `ball_trajectory` records samples within that interval; `player_trajectories` contains compact tuples `[offset_ms, x, y, facing_radians]` for every player, including integration and collision knots. Unchanged holds omit redundant interior knots. Samples include the contact state. Coordinates are metres on the 105 x 68 pitch; ball height is height above the ground.

The 3D renderer samples these paths and facing values without applying a cosmetic catch-up offset to the ball. Older fixtures without paths fall back to endpoint interpolation. Pose changes use recorded preparation and receiving/block/save actions. Orbiting changes the view only. Replay timers use actual intervals, so contact frames do not slow a passage down. The 2D view uses the same frame endpoints.

Ball-follow cameras permit orbit and zoom without dropping tracking. Full pitch is a fixed overview; turn off Follow Ball for free panning. Pitch labels and shirt backs use metadata shirt numbers, with names and roles in the expandable lineup. Fictional identity does not depend on the internal tracking ID.

The match transport retains footage received during the current session. Dragging the time-based slider or stepping ten seconds pauses the view at the chosen frame. Play View runs recorded movement at 1×; Return Live switches to the latest received frame. Live score, metrics and commentary continue independently, as the transport explains. Evidence inspection uses only its pinned replay window. This is a tracking review feature, not a server-side rewind of the simulation or a persistent recording library.

Additional frames participate in the metrics stream and evidence recomputation. Published insights retain their pinned snapshots; historical inspection excludes frames later than the selected moment. Existing generated sample files are not automatically migrated; generate new fixtures for the shared simulation.

## Limits and release review

This is an original lightweight football model, not a professional football game engine. Tactical decisions, offside, player separation, goalkeeper reach, rebound ownership and restarts are approximations. Some non-contact scenario events such as scripted disciplinary incidents remain director-controlled. Scripted attacks encourage attacking decisions; they no longer manufacture possession changes or bypass physical ball contacts. Exact seeded scores and scripted timing can change from previous versions.

Playback starts before the full fixture is generated. Regression tests require the first live input within five seconds and check bounded buffering, shutdown and parity with offline generation. This is a startup budget, not a claim that a complete match can be computed in five seconds. Swept player contacts and recording all players still increase generation, stream and rewind-memory costs compared with the earlier preview. CPU generation and browser GPU rendering require separate review on the deployed service. Colliders approximate bodies with upright volumes, rather than matching every animated limb triangle.

The full-match statistical and workload checks are expensive. Property checks for stream coherence and coordinate bounds use short two-period fixtures while retaining their generated seed examples. Full-match invariants, player workload and the 50-seed statistical sweep still simulate complete matches. Workload uses distance per 90 minutes, accounting for added time; its 7-13 km target is unchanged. The sweep reports per-seed totals, possession, red cards and the longest event gap so a stalled restart cannot disappear inside an average.

The implementation was informed by reading PitchLens's fixed-step/contact-driven approach, without importing its code or character assets. Kellan retains its own world model, orbitable scene, deterministic metric recomputation and Microsoft Agent Framework publication workflow.

Lint, type checking, production build and local fixture/browser observations should be reported separately from automated regression tests and live Foundry execution. Do not treat local mock-generated commentary as live model evidence.
