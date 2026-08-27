"""PDF 壓縮工具 進入點。串接 Model / View / Presenter（MVP 架構）。"""

from model import PdfCompressorModel
from presenter import PdfCompressorPresenter
from view import PdfCompressorView


def main() -> None:
    view = PdfCompressorView()
    model = PdfCompressorModel()
    presenter = PdfCompressorPresenter(view, model)

    try:
        view.run()
    finally:
        presenter.shutdown()


if __name__ == "__main__":
    main()
