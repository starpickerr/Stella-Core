from channel.weixin.weixin_channel import _poll_failure_delay


def test_weixin_poll_failures_back_off_and_cap():
    assert [_poll_failure_delay(count) for count in (1, 2, 3, 5, 6, 9, 12, 15)] == [
        2, 2, 30, 30, 60, 120, 240, 300,
    ]
