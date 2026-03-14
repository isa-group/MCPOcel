import logging
from shared.ocel.builder import OCELBuilder

logger = logging.getLogger(__name__)


def print_pipeline_audit(builder: OCELBuilder) -> None:
    cursor = builder.cursor

    cursor.execute("SELECT ocel_type, COUNT(*) FROM event GROUP BY ocel_type ORDER BY COUNT(*) DESC")
    e_types = cursor.fetchall()
    cursor.execute("SELECT ocel_type, COUNT(*) FROM object GROUP BY ocel_type ORDER BY COUNT(*) DESC")
    o_types = cursor.fetchall()

    logger.info("=" * 60)
    logger.info(f"{'GITHUB EXTRACTION REPORT':^60}")
    logger.info("=" * 60)

    logger.info(f"\n[EVENTS] Total: {sum(row[1] for row in e_types)}")
    for name, count in e_types:
        logger.info(f"  - {name:<35} | {count:>7}")

    logger.info(f"\n[OBJECTS] Total: {sum(row[1] for row in o_types)}")
    for name, count in o_types:
        logger.info(f"  - {name:<35} | {count:>7}")

    # CI/CD
    logger.info("\n[CI/CD: WorkflowRun → WorkflowJob]")
    cursor.execute("""
        SELECT COUNT(DISTINCT ocel_source_id)
        FROM object_object
        WHERE ocel_qualifier = 'job_of_run'
    """)
    linked_jobs = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM object WHERE ocel_type = 'WorkflowJob'")
    total_jobs = cursor.fetchone()[0]
    if total_jobs > 0:
        logger.info(f"  Jobs linked to a run : {linked_jobs}/{total_jobs} ({linked_jobs/total_jobs*100:.1f}%)")

    # Commits
    logger.info("\n[COMMITS]")
    cursor.execute("SELECT COUNT(*) FROM object WHERE ocel_type = 'Commit'")
    total_commit_objs = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM event WHERE ocel_type = 'CommitCreated'")
    total_commit_events = cursor.fetchone()[0]
    logger.info(f"  Commit objects       : {total_commit_objs}")
    logger.info(f"  CommitCreated events : {total_commit_events}")
    if total_commit_objs > total_commit_events:
        logger.info(f"  PR-only commits      : {total_commit_objs - total_commit_events}  (inserted via PR O2O, no push event)")

    cursor.execute("""
        SELECT COUNT(DISTINCT oo.ocel_target_id)
        FROM object_object oo
        JOIN object o ON oo.ocel_target_id = o.ocel_id
        WHERE o.ocel_type = 'Commit'
          AND oo.ocel_qualifier = 'contains_commit'
    """)
    commits_in_prs = cursor.fetchone()[0]
    if total_commit_objs > 0:
        logger.info(f"  Commits linked to PR : {commits_in_prs}/{total_commit_objs} ({commits_in_prs/total_commit_objs*100:.1f}%)")
        logger.info(f"  Direct push commits  : {total_commit_objs - commits_in_prs}")

    # Merge commit stats
    cursor.execute("""
        SELECT COUNT(*) FROM object_map
        WHERE ocel_type = 'Commit' AND ocel_key = 'is_merge_commit' AND ocel_value = '1'
    """)
    try:
        merge_commits = cursor.fetchone()[0]
        if merge_commits > 0:
            logger.info(f"  Merge commits        : {merge_commits}")
    except Exception:
        pass

    # Files
    cursor.execute("SELECT COUNT(*) FROM object WHERE ocel_type = 'File'")
    total_files = cursor.fetchone()[0]
    if total_files > 0:
        logger.info("\n[FILES]")
        logger.info(f"  File objects         : {total_files}")

        cursor.execute("""
            SELECT COUNT(*)
            FROM object_object oo
            JOIN object o ON oo.ocel_source_id = o.ocel_id
            WHERE o.ocel_type = 'Commit'
              AND oo.ocel_qualifier LIKE 'modifies_file_%'
        """)
        file_links = cursor.fetchone()[0]
        logger.info(f"  Commit→File links    : {file_links}")

        cursor.execute("""
            SELECT COUNT(*)
            FROM object_object oo
            JOIN object src ON oo.ocel_source_id = src.ocel_id
            WHERE src.ocel_type = 'Comment'
              AND oo.ocel_qualifier = 'on_file'
        """)
        comment_file_links = cursor.fetchone()[0]
        if comment_file_links > 0:
            logger.info(f"  Comment→File links   : {comment_file_links}")

        cursor.execute("""
            SELECT COUNT(*)
            FROM object_object oo
            JOIN object o ON oo.ocel_source_id = o.ocel_id
            WHERE o.ocel_type = 'Commit'
              AND oo.ocel_qualifier = 'modifies_file_renamed'
        """)
        renames = cursor.fetchone()[0]
        if renames > 0:
            logger.info(f"  Renames tracked      : {renames}")

    # Comments
    cursor.execute("SELECT COUNT(*) FROM object WHERE ocel_type = 'Comment'")
    total_comments = cursor.fetchone()[0]
    if total_comments > 0:
        logger.info("\n[COMMENTS]")
        logger.info(f"  Comment objects      : {total_comments}")
        logger.info(f"  CommentCreated events: {total_comments}")  # 1:1 by design

        # Breakdown by comment_type attribute
        cursor.execute("""
            SELECT ocel_value, COUNT(DISTINCT ocel_id)
            FROM object_map
            WHERE ocel_type = 'Comment' AND ocel_key = 'comment_type'
            GROUP BY ocel_value
            ORDER BY COUNT(DISTINCT ocel_id) DESC
        """)
        for ctype, count in cursor.fetchall():
            logger.info(f"    {ctype:<10}: {count:>5}")

        # Comment → Comment (replies_to)
        cursor.execute("""
            SELECT COUNT(*)
            FROM object_object oo
            JOIN object src ON oo.ocel_source_id = src.ocel_id
            WHERE src.ocel_type = 'Comment'
              AND oo.ocel_qualifier = 'replies_to'
        """)
        replies = cursor.fetchone()[0]
        if replies > 0:
            logger.info(f"  Reply threads        : {replies}")

    # Reviews
    cursor.execute("SELECT COUNT(*) FROM object WHERE ocel_type = 'Review'")
    total_reviews = cursor.fetchone()[0]
    if total_reviews > 0:
        logger.info("\n[REVIEWS]")
        logger.info(f"  Review objects       : {total_reviews}")

        cursor.execute("SELECT COUNT(*) FROM event WHERE ocel_type = 'ReviewThreadResolved'")
        threads_resolved = cursor.fetchone()[0]
        if threads_resolved > 0:
            logger.info(f"  Threads resolved     : {threads_resolved}")

        # Review state breakdown
        cursor.execute("""
            SELECT ocel_value, COUNT(DISTINCT ocel_id)
            FROM object_map
            WHERE ocel_type = 'Review' AND ocel_key = 'state'
            GROUP BY ocel_value
            ORDER BY COUNT(DISTINCT ocel_id) DESC
        """)
        states = cursor.fetchall()
        if states:
            logger.info(f"  By state: " + ", ".join(f"{s}={c}" for s, c in states))

    logger.info("=" * 60)