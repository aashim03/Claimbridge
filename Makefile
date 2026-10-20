CB = cd backend && uv run python -m claimbridge.cli

.PHONY: db generate reset selfcheck run gate test up down

db:            ## start FalkorDB only
	docker compose up -d falkordb

generate:      ## rebuild data/generated from the YAML (deterministic)
	$(CB) generate

reset:         ## drop and reseed the graph
	$(CB) reset

selfcheck:     ## does each trap fool nearest-neighbour reuse?
	$(CB) selfcheck

run:           ## run every evaluation claim through the agents
	$(CB) run all

gate:          ## Phase 1 gate: traps end to end + crash/resume
	$(CB) gate

test:
	cd backend && uv run pytest -q

up:            ## database + seed + agent workers in containers
	docker compose --profile agents up -d --build

down:
	docker compose --profile agents down

.PHONY: agents gate2
agents:        ## supervisor + worker pool in the foreground
	$(CB) up

gate2:         ## Phase 2 gate: full loop, guard, memory, contradiction, kill/resume, staleness
	$(CB) gate2

.PHONY: eval eval-report
eval:          ## Phase 3: ClaimBridge vs no-memory vs baseline RAG (+ large embeddings), chaos run
	$(CB) eval all

eval-report:   ## rebuild eval/results/latest.md from saved raw results
	$(CB) eval report
