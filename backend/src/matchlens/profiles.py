from matchlens.models.profiles import ViewerProfile

DEFAULT_PROFILES = (
    ViewerProfile(
        profile_id="analyst_en",
        label="Analyst",
        mode="analyst",
        language="en",
        favorite_team_id=None,
        favorite_player_id=None,
        focus_metric=None,
        verbosity="detailed",
    ),
    ViewerProfile(
        profile_id="casual_en",
        label="Casual",
        mode="casual",
        language="en",
        favorite_team_id=None,
        favorite_player_id=None,
        focus_metric=None,
        verbosity="short",
    ),
    ViewerProfile(
        profile_id="casual_es",
        label="Casual (es)",
        mode="casual",
        language="es",
        favorite_team_id=None,
        favorite_player_id=None,
        focus_metric=None,
        verbosity="short",
    ),
    ViewerProfile(
        profile_id="player_focus",
        label="Home No. 9",
        mode="player_focus",
        language="en",
        favorite_team_id="home",
        favorite_player_id="h09",
        focus_metric=None,
        verbosity="standard",
    ),
)

_PROFILES_BY_ID = {profile.profile_id: profile for profile in DEFAULT_PROFILES}


def get_profile(profile_id: str) -> ViewerProfile | None:
    return _PROFILES_BY_ID.get(profile_id)
