from github2ocel.transform.builder import OCELBuilder

def print_pipeline_audit(builder: OCELBuilder):
    cursor = builder.cursor

    # General Counts
    cursor.execute("SELECT ocel_type, COUNT(*) FROM event GROUP BY ocel_type")
    e_types = cursor.fetchall()
    cursor.execute("SELECT ocel_type, COUNT(*) FROM object GROUP BY ocel_type")
    o_types = cursor.fetchall()

    print("\n" + "="*60)
    print(f"{'GITHUB EXTRACTION REPORT':^60}")
    print("="*60)

    # Summary Events
    print(f"\n[EVENTS] Total: {sum(row[1] for row in e_types)}")
    for name, count in e_types:
        print(f"  - {name:<30} | {count:>7}")

    # Summary Objects
    print(f"\n[OBJECTS] Total: {sum(row[1] for row in o_types)}")
    for name, count in o_types:
        print(f"  - {name:<30} | {count:>7}")

    # Action Check (Workflow -> Jobs)
    print("\n[VÍNCULOS DE CI/CD: Workflow -> Jobs]")
    cursor.execute("""
        SELECT COUNT(DISTINCT e.ocel_id)
        FROM event e
        JOIN event_object eo ON e.ocel_id = eo.ocel_event_id
        JOIN object o ON eo.ocel_object_id = o.ocel_id
        WHERE e.ocel_type LIKE '%job%' AND o.ocel_type = 'WorkflowRun'
    """)
    linked_jobs = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM event WHERE ocel_type LIKE '%job%'")
    total_jobs = cursor.fetchone()[0]

    if total_jobs > 0:
        ratio = (linked_jobs / total_jobs) * 100
        print(f"Jobs ratio: {linked_jobs}/{total_jobs} ({ratio:.1f}%)")

    # Development Check (Commits -> Pull Requests)
    print("\n[DEVELOPMENT LINKS: Commits -> PRs]")
    cursor.execute("""
        SELECT COUNT(DISTINCT e.ocel_id)
        FROM event e
        JOIN event_object eo ON e.ocel_id = eo.ocel_event_id
        JOIN object o ON eo.ocel_object_id = o.ocel_id
        WHERE e.ocel_type = 'Commit' AND o.ocel_type = 'PullRequest'
    """)
    linked_commits = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM event WHERE ocel_type = 'Commit'")
    total_commits = cursor.fetchone()[0]

    if total_commits > 0:
        c_ratio = (linked_commits / total_commits) * 100
        print(f"Commits associated with PRs: {linked_commits}/{total_commits} ({c_ratio:.1f}%)")
        print(f"Direct commits (push to main): {total_commits - linked_commits}")

    print("\n" + "="*60 + "\n")