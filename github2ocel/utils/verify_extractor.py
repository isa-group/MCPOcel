import logging

logger = logging.getLogger(__name__)


def verify_data_integrity(extractor_stats: dict, builder_stats: dict) -> dict:
    """
    Compares extracted data statistics against the entities injected
    into the OCEL Builder layer.
    """

    logger.info("=" * 60)
    logger.info(f"{'INTEGRITY & AUDIT REPORT (OCEL 2.0)':^60}")
    logger.info("=" * 60)

    # 1. Global Reconciliation
    total_extracted = sum(extractor_stats.values())
    total_events = builder_stats.get("events", 0)
    total_objects = builder_stats.get("objects", 0)
    total_relationships = builder_stats.get("relationships", 0)

    logger.info("\n[GLOBAL RECONCILIATION]")
    logger.info(f"  - Total Entities Extracted: {total_extracted:>8}")
    logger.info(f"  - Total Events Injected:    {total_events:>8}")
    logger.info(f"  - Total Objects Created:    {total_objects:>8}")
    logger.info(f"  - Total Relationships:      {total_relationships:>8}")

    # 2. Discrepancy Analysis
    discrepancy = total_extracted - total_events

    if discrepancy == 0:
        status = "perfect_match"
        logger.info("  RECONCILIATION SUCCESS: Perfect entity alignment.")
    elif discrepancy > 0:
        status = "missing_records"
        logger.warning(f"  DISCREPANCY: {discrepancy} extracted records not injected.")
        logger.warning("      Possible causes: validation rejection, duplicate IDs, filtering.")
    else:
        status = "over_injection"
        logger.warning(f"  WARNING: {abs(discrepancy)} more events than extracted entities.")
        logger.warning("      Possible cause: lifecycle expansion (1 entity → multiple events).")

    success_ratio = (
        total_events / total_extracted
        if total_extracted > 0 else 0
    )
    logger.info(f"  - Injection Success Ratio:  {success_ratio:.2%}")

    # 3. Development-Level Breakdown
    if any(k in extractor_stats for k in ("commits", "issues")):
        logger.info("\n[DEVELOPMENT LINKS]")
        commits_ext = extractor_stats.get("commits", 0)
        issues_ext  = extractor_stats.get("issues", 0)
        prs_ext     = extractor_stats.get("prs", 0)
        issues_prs  = issues_ext + prs_ext

        logger.info(f"    - Commits Extracted:      {commits_ext}")
        logger.info(f"    - Issues Extracted:       {issues_ext}")
        logger.info(f"    - PRs Extracted:          {prs_ext}")

        if issues_prs > 0:
            pr_commit_links = extractor_stats.get("pr_commit_links", 0)
            issue_pr_rels = (
                extractor_stats.get("issue_comments", 0) +
                extractor_stats.get("pr_comments", 0) +
                extractor_stats.get("reviews", 0) +
                extractor_stats.get("timeline_events", 0) +
                pr_commit_links
            )
            rel_density = issue_pr_rels / issues_prs
            logger.info(f"    - Relationships (issue/PR-scoped): {issue_pr_rels}")
            logger.info(f"    - Avg Relationships per Issue/PR:  {rel_density:.2f}")

    # 4. DevOps / CI-CD Breakdown
    if "runs" in extractor_stats:
        logger.info("\n[CI/CD DEVOPS LINKS]")
        runs_ext = extractor_stats.get("runs", 0)
        logger.info(f"    - Workflow Runs Extracted: {runs_ext}")
        logger.info(f"    - Total Process Events:    {total_events}")
        lifecycle_expansion_ratio = (
            total_events / runs_ext
            if runs_ext > 0 else 0
        )
        logger.info(f"    - Avg Events per Run:      {lifecycle_expansion_ratio:.2f}")

    logger.info("=" * 60)

    return {
        "total_extracted": total_extracted,
        "total_events": total_events,
        "total_objects": total_objects,
        "total_relationships": total_relationships,
        "discrepancy": discrepancy,
        "status": status,
        "success_ratio": success_ratio,
    }