from meetily_detector.signals import browsers


def test_list_all_tabs_only_queries_running_browsers():
    queried = []

    def fake_is_running(name):
        return name in ("Google Chrome",)

    def fake_run(script):
        queried.append(script)
        return "true\thttps://meet.google.com/abc-defg-hij\tStandup"

    tabs = browsers.list_all_tabs(run=fake_run, is_running=fake_is_running)
    # Only one browser was running -> only one osascript invocation.
    assert len(queried) == 1
    assert len(tabs) == 1
    assert tabs[0]["url"] == "https://meet.google.com/abc-defg-hij"
    assert tabs[0]["browser"] == "Google Chrome"
    assert tabs[0]["frontmost"] is True


def test_list_all_tabs_aggregates_multiple_browsers():
    def fake_is_running(name):
        return name in ("Safari", "Brave Browser")

    def fake_run(script):
        return "false\thttps://meet.google.com/xyz-abcd-efg\tRetro"

    tabs = browsers.list_all_tabs(run=fake_run, is_running=fake_is_running)
    assert len(tabs) == 2
    assert {t["browser"] for t in tabs} == {"Safari", "Brave Browser"}


def test_list_all_tabs_none_running():
    tabs = browsers.list_all_tabs(run=lambda s: "", is_running=lambda n: False)
    assert tabs == []


def test_running_browser_error_is_skipped_not_fatal():
    def fake_run(script):
        raise RuntimeError("not authorized")

    tabs = browsers.list_all_tabs(run=fake_run, is_running=lambda n: n == "Safari")
    assert tabs == []  # error logged, no crash
