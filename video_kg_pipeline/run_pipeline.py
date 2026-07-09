"""Orchestrates the video -> knowledge-graph pipeline.

Stage 1 always runs stage 1b (terminology/unit correction) immediately
afterwards - there's no separate --stage number for it since it's a fixed
post-processing step on stage 1's own output, not an independently useful
stage. Run `python stage1b_correct_terminology.py` directly if you only want
to re-apply the dictionary without re-transcribing.

Usage:
    python run_pipeline.py                    # stages 1-5, respects TEST_MODE in .env
    python run_pipeline.py --stage 2          # run only stage 2 (debugging one stage)
    python run_pipeline.py --from-stage 3     # resume from stage 3, reusing existing outputs/0{1,2}_*.json
    python run_pipeline.py --stage 6          # just (re)build the graph visualization from 05_knowledge_graph.json
    python run_pipeline.py --full             # ignore TEST_MODE, process the whole video, and auto-append stage 6
"""
import argparse

import config
import stage1_asr
import stage1b_correct_terminology
import stage2_extract
import stage3_keyframes
import stage4_visual
import stage5_bind
import stage6_visualize_kg

STAGES = {
    1: ("ASR transcription", stage1_asr.run),
    2: ("Triple extraction", stage2_extract.run),
    3: ("Keyframe localization", stage3_keyframes.run),
    4: ("Visual analysis", stage4_visual.run),
    5: ("Knowledge graph binding", stage5_bind.run),
    6: ("Knowledge graph visualization (optional)", stage6_visualize_kg.run),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Video -> knowledge graph pipeline")
    parser.add_argument("--stage", type=int, choices=STAGES.keys(), help="Run only this single stage")
    parser.add_argument("--from-stage", type=int, default=1, choices=STAGES.keys())
    parser.add_argument("--to-stage", type=int, default=5, choices=STAGES.keys())
    parser.add_argument("--full", action="store_true", help="Ignore TEST_MODE, process the whole video, and auto-append stage 6 (graph visualization)")
    args = parser.parse_args()

    logger = config.setup_logging("run_pipeline")
    stage_range = [args.stage] if args.stage else list(range(args.from_stage, args.to_stage + 1))
    if args.full and 6 not in stage_range:
        stage_range.append(6)

    for stage_num in stage_range:
        name, func = STAGES[stage_num]
        logger.info("=" * 60)
        logger.info("STAGE %d: %s", stage_num, name)
        logger.info("=" * 60)
        if stage_num == 1:
            func(test_mode=False if args.full else None)
            logger.info("-" * 60)
            logger.info("STAGE 1b: Terminology/unit correction")
            logger.info("-" * 60)
            stage1b_correct_terminology.run()
        else:
            func()

    logger.info("Pipeline complete.")


if __name__ == "__main__":
    main()
