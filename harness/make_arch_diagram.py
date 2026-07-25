"""fig_pipeline.png -- Paper 5 ground-truth AIOps benchmark pipeline.

Injected fault (known root cause) -> evidence bundle -> open-LLM diagnosers ->
deterministic rubric grade. Requires graphviz `dot`.
Run: python make_arch_diagram.py
"""

from diagrams import Cluster, Diagram, Edge
from diagrams.programming.language import Python
from diagrams.generic.storage import Storage
from diagrams.onprem.compute import Server
from diagrams.k8s.compute import Pod

graph_attr = {"dpi": "300", "fontsize": "13", "pad": "0.2", "splines": "spline",
              "nodesep": "0.35", "ranksep": "0.6"}
node_attr = {"fontsize": "11"}

with Diagram("", filename="fig_pipeline", outformat="png", show=False,
             graph_attr=graph_attr, node_attr=node_attr, direction="LR"):

    corpus = Python("corpus.py\n26 injected faults\nKNOWN root cause + fix\nclassic + P2/P3/P7 findings")

    with Cluster("k3s cluster (vast.ai VM)"):
        inject = Pod("apply + inject\nsettle -> failure manifests")
        cap = Python("capture.py\ndescribe/events/logs/\nworkloads/annotations\nsanitized")

    bundles = Storage("26 evidence bundles\n(the citable dataset)\nground truth withheld")

    with Cluster("open-LLM diagnosers (RTX 4090)"):
        models = Server("Qwen2.5 7B/14B/32B\nLlama3.1-8B, Gemma2-9B\nvia Ollama /v1")

    with Cluster("grading (blind, deterministic)"):
        rubric = Python("rubric.py\nconcept-group + forbidden\nexact/category/wrong/halluc")
        analyze = Python("analyze.py\nRQ1 acc + by-category\nRQ2 evidence, RQ4 cost")

    out = Storage("results.md\n+ figures")

    corpus >> inject >> cap >> bundles
    bundles >> Edge(label="evidence only") >> models
    corpus >> Edge(label="answer key", style="dashed") >> rubric
    models >> Edge(label="diagnoses") >> rubric >> analyze >> out
