1.Help me build a student transportation assignment and operations system.
The goal is to assign students to routes and stops while respecting bus capacity, pickup windows, accessibility needs, safety rules, and daily attendance updates. It should expose decisions and exceptions, preserve history, and report measurable outcomes.

Actors: learners/guardians, instructors, academic administrators, support staff, and platform administrators.

Required entities: Student, GuardianContact, AddressZone, Stop, Bus, Driver, Route, RouteStop, Assignment, AttendanceEvent, Notification. Every entity needs a primary key; relationships need foreign keys, documented cardinality, lifecycle states, and effective dates. Use bridge tables for many-to-many relationships and events for historical state changes.

Data must be synthetic. Use deterministic IDs, a fixed seed (20261022), and a parameterized generator that supports both a small starter dataset and a full dataset of 5,000 students, 100 buses, 300 stops, and 200 school days. Generate valid baseline data first, then add clearly labeled edge cases. Keep ground-truth labels separate from input data.

Edge cases: bus capacity exceeded, incompatible route assignment, impossible travel time between stops, invalid notification contact, and unapproved address exposure.

2.Before writing code, inspect the project and propose:
1. Requirements and any ambiguities
2. Architecture and recommended stack
3. Data model and relationship/cardinality summary
4. Assignment and validation rules
5. API/UI scope, if applicable
6. Testing and evaluation plan
7. Risks, assumptions, and implementation milestones
Do not modify files yet. Ask me only about choices that materially affect the design; otherwise state reasonable assumptions.


3. Steps to perform sequencialy


4. Using the approved plan, design the database schema and data dictionary for:
Student, GuardianContact, AddressZone, Stop, Bus, Driver, Route, RouteStop, Assignment, AttendanceEvent, and Notification.

5. For every field specify type, required/optional, allowed values, units, uniqueness, validation rule, and whether it contains sensitive data. Document primary and foreign keys, relationship cardinality, optional relationships, effective dates, and lifecycle states.

7. Define the business rules for capacity, accessibility, pickup windows, route feasibility, attendance, missed pickups, guardian notifications, and approved addresses. Define how invalid cases are recorded without corrupting otherwise valid records. Keep ground truth separate from operational input data.

8. Avoid the repeatitive task which are not necessary, focus on the priority task

9. Provide me with command wherever required

10. Also used copilot as I was working on vscode for realtime errors. 

11. Verify the whole project before submission