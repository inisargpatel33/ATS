from ortools.sat.python import cp_model

def generate_timetable():
    # 1. Initialize the CP-SAT Model
    model = cp_model.CpModel()

    # 2. Define Dummy Data (Simulating Database Inputs)
    # Change this line in your solver_core.py:
   # 2. Define Balanced Dummy Data
    days = ["Mon", "Tue", "Wed", "Thu", "Fri"] # 5 days
    slots = ["Slot1", "Slot2", "Slot3"]  
    rooms = ["Room_301", "Room_302"]
    batches = ["MCA_Sem2", "BCA_Sem4", "MCA_Sem4"]
    
    # Subjects & Their required hours for the week
    subjects = {
        "Java": {"hours": 2, "room_type": "regular"},
        "Python": {"hours": 2, "room_type": "regular"},
        "Web_Sec": {"hours": 2, "room_type": "regular"}
    }

    # Faculty profiles - EXPANDED MAX HOURS to comfortably fit the 18-hour demand
    faculty_profiles = {
        "Prof_Sharma": {"max_hours": 8, "expertise": {"Java": 1.0, "Python": 0.5}},
        "Prof_Verma": {"max_hours": 8, "expertise": {"Python": 1.0, "Web_Sec": 0.5}},
        "Prof_Mehta": {"max_hours": 8, "expertise": {"Web_Sec": 1.0, "Java": 0.5}}
    }

    # 3. Create Decision Variables
    # x[f, s, r, d, t, b] = 1 if assigned, 0 otherwise
    x = {}
    for f in faculty_profiles:
        for s in subjects:
            for r in rooms:
                for d in days:
                    for t in slots:
                        for b in batches:
                            # Only create a variable if the faculty is actually qualified to teach the subject
                            if s in faculty_profiles[f]["expertise"]:
                                x[f, s, r, d, t, b] = model.NewBoolVar(f'x_{f}_{s}_{r}_{d}_{t}_{b}')

    # 4. Apply HARD CONSTRAINTS
    
    # Rule A: Faculty Clash Avoidance (A professor can only be in one place at a time)
    for f in faculty_profiles:
        for d in days:
            for t in slots:
                model.AddAtMostOne(
                    x[f, s, r, d, t, b] 
                    for s in subjects for r in rooms for b in batches 
                    if (f, s, r, d, t, b) in x
                )

    # Rule B: Room Clash Avoidance (A room can hold at most one class at a time)
    for r in rooms:
        for d in days:
            for t in slots:
                model.AddAtMostOne(
                    x[f, s, r, d, t, b] 
                    for f in faculty_profiles for s in subjects for b in batches 
                    if (f, s, r, d, t, b) in x
                )

    # Rule C: Batch Cohesion (A student batch cannot attend two lectures at once)
    for b in batches:
        for d in days:
            for t in slots:
                model.AddAtMostOne(
                    x[f, s, r, d, t, b] 
                    for f in faculty_profiles for s in subjects for r in rooms 
                    if (f, s, r, d, t, b) in x
                )

    # Rule D: Syllabus Requirements (Every subject for a batch must hit its target weekly hours)
    for b in batches:
        for s in subjects:
            model.Add(
                sum(x[f, s, r, d, t, b] 
                    for f in faculty_profiles for r in rooms for d in days for t in slots 
                    if (f, s, r, d, t, b) in x) == subjects[s]["hours"]
            )

    # Rule E: Faculty Workload Capping (Do not exceed maximum weekly contract hours)
    for f in faculty_profiles:
        model.Add(
            sum(x[f, s, r, d, t, b] 
                for s in subjects for r in rooms for d in days for t in slots for b in batches 
                if (f, s, r, d, t, b) in x) <= faculty_profiles[f]["max_hours"]
        )

    # 5. Apply SOFT CONSTRAINTS (Optimization Objective)
    # We want to maximize the use of "Primary Experts" over "Secondary Backups"
    objective_terms = []
    for (f, s, r, d, t, b), var in x.items():
        weight = int(faculty_profiles[f]["expertise"][s] * 10) # 1.0 becomes weight 10, 0.5 becomes weight 5
        objective_terms.append(var * weight)
        
    model.Maximize(sum(objective_terms))

    # 6. Run the Mathematical Solver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0  # Cap execution time
    status = solver.Solve(model)

    # 7. Output Result
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print(f"Timetable successfully generated! (Status: {solver.StatusName(status)})\n")
        print(f"{'Day':<6} | {'Slot':<6} | {'Room':<10} | {'Batch':<10} | {'Subject':<10} | {'Faculty':<12}")
        print("-" * 65)
        
        for d in days:
            for t in slots:
                for r in rooms:
                    for f in faculty_profiles:
                        for s in subjects:
                            for b in batches:
                                if (f, s, r, d, t, b) in x and solver.Value(x[f, s, r, d, t, b]) == 1:
                                    print(f"{d:<6} | {t:<6} | {r:<10} | {b:<10} | {s:<10} | {f:<12}")
    else:
        print("No valid timetable arrangement could satisfy these constraints.")

if __name__ == "__main__":
    generate_timetable()