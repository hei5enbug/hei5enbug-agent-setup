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
