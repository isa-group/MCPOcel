from shared.ocel.builder import OCELBuilder

def print_pipeline_audit(builder: OCELBuilder):
    cursor = builder.cursor

    cursor.execute("SELECT ocel_type, COUNT(*) FROM event GROUP BY ocel_type ORDER BY COUNT(*) DESC")
    e_types = cursor.fetchall()
    cursor.execute("SELECT ocel_type, COUNT(*) FROM object GROUP BY ocel_type ORDER BY COUNT(*) DESC")
    o_types = cursor.fetchall()

    print("\n" + "="*60)
    print(f"{'GITHUB EXTRACTION REPORT':^60}")
    print("="*60)

    print(f"\n[EVENTS] Total: {sum(row[1] for row in e_types)}")
    for name, count in e_types:
        print(f"  - {name:<35} | {count:>7}")

    print(f"\n[OBJECTS] Total: {sum(row[1] for row in o_types)}")
    for name, count in o_types:
        print(f"  - {name:<35} | {count:>7}")

    # CI/CD: Workflow -> Jobs
    print("\n[CI/CD: WorkflowRun → WorkflowJob]")
    cursor.execute("""
        SELECT COUNT(DISTINCT ocel_source_id)
        FROM object_object
        WHERE ocel_qualifier = 'job_of_run'
    """)
    linked_jobs = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM object WHERE ocel_type = 'WorkflowJob'")
    total_jobs = cursor.fetchone()[0]
    if total_jobs > 0:
        print(f"  Jobs linked to a run : {linked_jobs}/{total_jobs} ({linked_jobs/total_jobs*100:.1f}%)")

    # Commits
    print("\n[COMMITS]")
    cursor.execute("SELECT COUNT(*) FROM object WHERE ocel_type = 'Commit'")
    total_commit_objs = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM event WHERE ocel_type = 'CommitCreated'")
    total_commit_events = cursor.fetchone()[0]
    # Commits from direct push (have CommitCreated event) vs embedded in PRs only
    print(f"  Commit objects       : {total_commit_objs}")
    print(f"  CommitCreated events : {total_commit_events}")
    if total_commit_objs > total_commit_events:
        print(f"  PR-only commits      : {total_commit_objs - total_commit_events}  (inserted via PR O2O, no push event)")

    # Commits -> PRs
    # Relation is PR→Commit (source=PR, target=Commit, qualifier='contains_commit')
    cursor.execute("""
        SELECT COUNT(DISTINCT oo.ocel_target_id)
        FROM object_object oo
        JOIN object o ON oo.ocel_target_id = o.ocel_id
        WHERE o.ocel_type = 'Commit'
          AND oo.ocel_qualifier = 'contains_commit'
    """)
    commits_in_prs = cursor.fetchone()[0]
    if total_commit_objs > 0:
        print(f"  Commits linked to PR : {commits_in_prs}/{total_commit_objs} ({commits_in_prs/total_commit_objs*100:.1f}%)")
        print(f"  Direct push commits  : {total_commit_objs - commits_in_prs}")

    # Files (only present in COMPLETE profile with small time window)
    cursor.execute("SELECT COUNT(*) FROM object WHERE ocel_type = 'File'")
    total_files = cursor.fetchone()[0]
    if total_files > 0:
        print("\n[FILES]")
        print(f"  File objects         : {total_files}")
        cursor.execute("""
            SELECT COUNT(*)
            FROM object_object oo
            JOIN object o ON oo.ocel_source_id = o.ocel_id
            WHERE o.ocel_type = 'Commit'
              AND oo.ocel_qualifier LIKE 'modifies_file_%'
        """)
        file_links = cursor.fetchone()[0]
        print(f"  Commit→File links    : {file_links}")
        cursor.execute("""
            SELECT COUNT(*)
            FROM object_object oo
            JOIN object o ON oo.ocel_source_id = o.ocel_id
            WHERE o.ocel_type = 'Commit'
              AND oo.ocel_qualifier = 'modifies_file_renamed'
        """)
        renames = cursor.fetchone()[0]
        if renames > 0:
            print(f"  Renames tracked      : {renames}")

    print("\n" + "="*60 + "\n")