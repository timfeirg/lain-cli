.PHONY: clean
clean:
	- find . -iname "*__pycache__" | xargs rm -rf
	- find . -iname "*.pyc" | xargs rm -rf
	- rm -rf dist build *.egg-info .coverage htmlcov unittest.xml .*cache _build _templates public

.PHONY: pip-compile
pip-compile:
	pip-compile -U -vvv --output-file=docker-image/requirements.txt docker-image/requirements.in

.PHONY: sphinx
sphinx:
	sphinx-build -b html docs public
