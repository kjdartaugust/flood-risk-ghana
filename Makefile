.PHONY: up down logs seed test lint train fmt

up:            ## build + start the full local stack
	docker compose up --build

down:          ## stop and remove containers
	docker compose down

logs:          ## tail backend + worker logs
	docker compose logs -f backend worker

seed:          ## (re)seed events, tiles, routes
	docker compose exec backend python -m app.etl.seed

train:         ## train the ML model (KIND=logistic|lightgbm)
	docker compose exec backend python -m app.ml.train --kind $(or $(KIND),logistic)

test:          ## run backend tests
	cd backend && pytest -q

lint:          ## ruff backend + tsc frontend
	cd backend && ruff check app
	cd frontend && npm run typecheck

fmt:           ## auto-fix lint
	cd backend && ruff check --fix app
