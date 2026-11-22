.PHONY: all run start stop restart logs status clean

all: run

run start:
	@./run.sh

stop:
	@docker compose down

restart:
	@docker compose restart

logs:
	@docker compose logs -f

status:
	@docker compose ps
