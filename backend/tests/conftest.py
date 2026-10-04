from hypothesis import settings

settings.register_profile("matchlens", derandomize=True, deadline=None, database=None)
settings.load_profile("matchlens")
