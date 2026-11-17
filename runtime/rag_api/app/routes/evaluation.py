"""評価モードの受け口（settings.eval_enabled のときだけ main.py で登録する）。"""

from fastapi import APIRouter

from ..schemas import EvalRecord
from ..services import evaluation

router = APIRouter(prefix="/eval")


@router.get("/questions")
def eval_questions():
    """入力: なし / 出力: {testset, questions: [{id, type, question}]}"""
    return evaluation.questions()


@router.get("/status")
def eval_status(run: str):
    """入力: ?run=記録名 / 出力: {run, recorded: {id: "done"|"skipped"}}"""
    return evaluation.status(run)


@router.post("/record")
def eval_record(body: EvalRecord):
    """入力: 1問分の結果（EvalRecord） / 出力: {ok, saved, count}"""
    return evaluation.record(body)
