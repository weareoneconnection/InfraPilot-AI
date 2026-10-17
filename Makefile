.PHONY: install run test eval
install:
	pip install -r requirements.txt
run:
	./run.sh
test:
	pytest -q
eval:
	python evals/run_eval.py
