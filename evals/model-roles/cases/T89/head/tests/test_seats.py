from seatmap import SeatMap


def test_hold_and_release():
    seats = SeatMap(capacity=2)
    assert seats.hold("A1", "ann")
    assert seats.holder("A1") == "ann"
    assert not seats.release("A1", "bob")
    assert seats.release("A1", "ann")
    assert seats.holder("A1") is None


def test_a_taken_seat_cannot_be_held_again():
    seats = SeatMap(capacity=2)
    assert seats.hold("A1", "ann")
    assert not seats.hold("A1", "bob")


def test_a_full_event_refuses_new_holds():
    seats = SeatMap(capacity=1)
    assert seats.hold("A1", "ann")
    assert not seats.hold("A2", "bob")


def test_hold_many_holds_the_whole_group():
    seats = SeatMap(capacity=4)
    assert seats.hold_many(["A1", "A2", "A3"], "ann")
    assert [seats.holder(seat) for seat in ("A1", "A2", "A3")] == ["ann", "ann", "ann"]


def test_hold_many_holds_none_when_one_seat_is_taken():
    seats = SeatMap(capacity=4)
    assert seats.hold("A2", "bob")
    assert not seats.hold_many(["A1", "A2"], "ann")
    assert seats.holder("A1") is None


def test_hold_many_refuses_a_group_larger_than_the_free_seats():
    seats = SeatMap(capacity=2)
    assert not seats.hold_many(["A1", "A2", "A3"], "ann")
    assert seats.holder("A1") is None
