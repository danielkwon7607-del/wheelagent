def pytest_configure(config):
    config.addinivalue_line("markers", "delta: run the test under the delta put rule (default: the 10% rule)")
