.PHONY: init up down logs rebuild ps shell-backend shell-frontend seed reset

COMPOSE := docker compose

init:
	@if [ ! -f backend/.env ]; then cp backend/.env.example backend/.env; fi
	@if ! grep -q '^BACKEND_PUBLIC_URL=' backend/.env; then printf '\nBACKEND_PUBLIC_URL=http://127.0.0.1:8000\n' >> backend/.env; fi

up: init
	$(COMPOSE) up --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

rebuild: init
	$(COMPOSE) up --build --force-recreate

ps:
	$(COMPOSE) ps

shell-backend:
	$(COMPOSE) exec backend /bin/bash

shell-frontend:
	$(COMPOSE) exec frontend /bin/bash

seed:
	$(COMPOSE) exec backend python -m app.scripts.seed_flights
	$(COMPOSE) exec backend python -m app.scripts.seed_bookings
	$(COMPOSE) exec backend python -m app.scripts.seed_knowledge

reset:
	$(COMPOSE) exec backend python -m app.scripts.reset_data
