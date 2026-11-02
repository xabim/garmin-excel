"""In-memory Garmin gateway: records every write so tests can assert on them."""
from garmin_excel.payload import hash_from_description


class FakeGateway:
    def __init__(self, existing=None):
        self.workouts = {}      # id -> payload
        self.calendar = set()   # (id, date)
        self.writes = []        # ("create"|"update"|"schedule", ...)
        self.fail_schedule_for = set()
        self._id = 1000
        for payload, dates in existing or []:
            wid = self._new(payload)
            self.calendar |= {(wid, d) for d in dates}

    def _new(self, payload):
        self._id += 1
        self.workouts[self._id] = payload
        return self._id

    def list_workouts(self):
        return [{"workoutId": i, "workoutName": p["workoutName"]} for i, p in self.workouts.items()]

    def get_workout(self, workout_id):
        return self.workouts[workout_id]

    def scheduled(self, year, month):
        return [{"itemType": "workout", "id": 5000 + i, "workoutId": i, "date": d} for i, d in self.calendar if d.startswith(f"{year}-{month:02d}")]

    def create(self, payload):
        self.writes.append(("create", payload["workoutName"]))
        return self._new(payload)

    def update(self, workout_id, payload):
        self.writes.append(("update", payload["workoutName"]))
        self.workouts[workout_id] = payload

    def schedule(self, workout_id, day):
        name = self.workouts[workout_id]["workoutName"]
        if name in self.fail_schedule_for:
            raise RuntimeError("boom")
        self.writes.append(("schedule", name, day))
        self.calendar.add((workout_id, day))

    def unschedule(self, scheduled_id):
        self.writes.append(("unschedule", scheduled_id))
        self.calendar = {(i, d) for i, d in self.calendar if 5000 + i != scheduled_id}

    def delete(self, workout_id):
        self.writes.append(("delete", self.workouts[workout_id]["workoutName"]))
        del self.workouts[workout_id]
