# Build and demo order

1. Install dependencies and run `uvicorn backend.main:app --reload`.
2. Generate a multi-vehicle plan and inspect Planner → Coordinator → Policy traces.
3. Approve; observe waypoint motion, heading and battery updates.
4. Inject a failure into an executing asset; inspect the degraded parent mission and recovery proposal.
5. Approve recovery; observe reassignment and parent mission completion.
6. Restart the server and verify SQLite restores fleet and mission history.
7. Optionally enable Gemini Developer API mode via local `.env`; do not commit the key.

This is a software simulation demo. PX4 SITL and physical vehicle control are outside the operational scope.
