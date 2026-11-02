"""Real-courseware question set with page-level gold annotations (ED-04 extension).

The questions target the six algorithm-course courseware files that are actually
indexed in the live ``edurage_chunks`` Qdrant collection used by ED-04.  Unlike
``tests/fixtures/retrieval_golden.py`` (a fully synthetic fixture whose only job
is to exercise fusion deterministically), every entry here is annotated against
the real corpus:

* ``document_id`` / ``course_code`` identify the indexed courseware document.
  Five PDFs belong to course code ``1``; the RNN deck belongs to course code
  ``2`` (verified by scrolling the live collection payloads on 2026-11-02).
* ``gold_pages`` lists the 1-based PDF page numbers whose indexed chunk text
  actually contains the answer.  Each page was verified by reading the payload
  ``text`` of the chunks returned by a Qdrant scroll filtered on
  ``document_id`` and ``page``; pages whose OCR was too noisy were replaced.
* ``reference_facts`` are short factual bullets used by the generation-layer
  faithfulness evaluation (see ``src/edurage/eval/faithfulness.py``).  They are
  paraphrased from the verified page text, not invented.

The set intentionally mixes question kinds (``kind``): definitions, algorithm
steps, state-transition equations, numeric examples, tables, figures,
comparisons and API usage.  Questions are written in natural Chinese and name
the concept explicitly enough for a healthy hybrid retriever to find the page.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Courseware document ids as stored in the live ``edurage_chunks`` collection.
DOC_DP1 = "1b9c7ea1-2b4e-4d0c-b6b5-f7cf80a572c4"
DOC_DP2 = "197c0fdb-9aee-4e95-9521-36297743bf38"
DOC_DP3 = "d0ad22bb-beed-4277-91ff-1fb999150ca7"
DOC_DP4 = "d3440dd2-ef7f-4149-a096-5a14cc934dd3"
DOC_GREEDY = "ecd5d538-6b48-4f87-bca5-61b8f29988b3"
DOC_RNN = "325bc8f1-18af-4958-96ed-8b1d16793b89"

# Course codes verified from live payloads: the five DP/greedy PDFs are "1",
# the RNN PPTX is "2".
COURSE_ALGORITHMS = "1"
COURSE_RNN = "2"

# ``pages`` is the number of PDF pages that carry indexed chunks (max page seen
# in the live collection for the document), not necessarily the slide count.
DOCUMENTS: dict[str, dict[str, Any]] = {
    DOC_DP1: {
        "filename": "算法设计与分析_第3章_动态规划1-发布版.pdf",
        "course_code": COURSE_ALGORITHMS,
        "pages": 75,
    },
    DOC_DP2: {
        "filename": "算法设计与分析_第3章_动态规划2-发布版.pdf",
        "course_code": COURSE_ALGORITHMS,
        "pages": 38,
    },
    DOC_DP3: {
        "filename": "算法设计与分析_第3章_动态规划3-发布版 - 副本.pdf",
        "course_code": COURSE_ALGORITHMS,
        "pages": 39,
    },
    DOC_DP4: {
        "filename": "算法设计与分析_第3章_动态规划4-发布版.pdf",
        "course_code": COURSE_ALGORITHMS,
        "pages": 51,
    },
    DOC_GREEDY: {
        "filename": "算法设计与分析_第4章_贪心算法1-发布版.pdf",
        "course_code": COURSE_ALGORITHMS,
        "pages": 41,
    },
    DOC_RNN: {
        "filename": "04-循环神经网络.pptx",
        "course_code": COURSE_RNN,
        "pages": 49,
    },
}

COURSEWARE_GOLDEN_QUESTIONS: tuple[dict[str, Any], ...] = (
    # ------------------------------------------------------------------ DP1
    {
        "id": "dp1-q01",
        "question": "用分治法求解多数元素（majority element）问题时，算法的时间复杂度是多少？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP1,
        "gold_pages": (3,),
        "kind": "complexity",
        "reference_facts": (
            "分治法 Majority(A[1,n]) 的复杂度分析为 T(n) = 2T(n/2) + O(n) = O(nlogn)",
            "该问题还存在线性时间的计数（Counting）算法",
        ),
    },
    {
        "id": "dp1-q02",
        "question": "分治法在子问题不独立时会出现什么问题？动态规划又是如何解决这个问题的？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP1,
        "gold_pages": (12,),
        "kind": "comparison",
        "reference_facts": (
            ("分治技术要求子问题相互独立；若子问题不独立，分治方法将重复计算公共子问题，效率很低，"
            "甚至在多项式量级的子问题数目时也可能耗费指数时间"),
            "动态规划的解决方案是用表来保存所有已解决子问题的答案",
        ),
    },
    {
        "id": "dp1-q03",
        "question": (
            "三矩阵连乘 A1(10×100)、A2(100×5)、A3(5×50)，分别按 ((A1A2)A3) 和 "
            "(A1(A2A3)) 两种方式加括号，总乘法次数各是多少？"
        ),
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP1,
        "gold_pages": (21,),
        "kind": "numeric_example",
        "reference_facts": (
            "((A1A2)A3) 的总乘法次数 = 10×100×5 + 10×5×50 = 5000 + 2500 = 7500",
            "(A1(A2A3)) 的总乘法次数 = 100×5×50 + 10×100×50 = 25000 + 50000 = 75000",
            "第一种加括号方式比第二种快 10 倍",
        ),
    },
    {
        "id": "dp1-q04",
        "question": (
            "设有四个矩阵 A(50×10)、B(10×40)、C(40×30)、D(30×5)，五种完全加括号方式中"
            "乘法次数最少的是哪一种，最少次数是多少？"
        ),
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP1,
        "gold_pages": (23,),
        "kind": "table",
        "reference_facts": (
            ("五种完全加括号方式及代价：(A((BC)D)) 16000、(A(B(CD))) 10500、((AB)(CD)) 36000、"
            "(((AB)C)D) 87500、((A(BC))D) 34500"),
            "代价最小的是 (A(B(CD)))，乘法次数为 10500",
        ),
    },
    {
        "id": "dp1-q05",
        "question": "矩阵连乘问题中，m[i,j] 表示什么？它的递归定义式是什么？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP1,
        "gold_pages": (40,),
        "kind": "equation",
        "reference_facts": (
            "m[i,j] 表示计算矩阵链 A[i..j] 所需的最少乘法次数，原问题最优值为 m[1,n]",
            "m[i,j] = min over i≤k<j { m[i,k] + m[k+1,j] + p_{i-1}·p_k·p_j }",
            "矩阵 Ai 的维数为 p_{i-1}×p_i",
        ),
    },
    {
        "id": "dp1-q06",
        "question": "矩阵连乘的备忘录算法 lookupChain 的时间复杂度和空间复杂度分别是多少？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP1,
        "gold_pages": (46,),
        "kind": "complexity",
        "reference_facts": (
            "时间复杂度为 O(n^3)：n^2 个子问题，每个子问题填入表的时间为 O(n)",
            "空间复杂度为 O(n^2)",
            "MemoizedMatrixChain 先把 m[i,j] 初始化为 ∞，再调用 lookupChain(a,1,n)",
        ),
    },
    {
        "id": "dp1-q07",
        "question": "备忘录方法与动态规划法在求解次数、结构形式和查表方式上有什么区别？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP1,
        "gold_pages": (63,),
        "kind": "table",
        "reference_facts": (
            "求解次数：动态规划法所有子问题都至少要解一次；备忘录法部分子问题可不必求解",
            "结构形式：动态规划法自底向上；备忘录法自顶向下",
            "查表方式：动态规划法先填后查；备忘录法先查后填",
            "两种方法都利用了子问题重叠性质",
        ),
    },
    # ------------------------------------------------------------------ DP2
    {
        "id": "dp2-q01",
        "question": "最长公共子序列问题中，子序列（subsequence）的定义是什么？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP2,
        "gold_pages": (7,),
        "kind": "definition",
        "reference_facts": (
            ("给定序列 X，若存在 X 索引的一个严格增序列 <i1,i2,...,ik>，使得对所有 j=1..k 都有 "
            "x[ij]=zj，则称 Z=<z1,z2,...,zk> 是 X 的子序列"),
            "例 X=A,B,C,B,D,A,B 时，Z=B,C,D,B 是子序列，其索引序列为 <2,3,5,7>",
        ),
    },
    {
        "id": "dp2-q02",
        "question": (
            "给定 X=<A,B,C,B,D,A,B> 和 Y=<B,D,C,A,B,A>，它们的最长公共子序列（LCS）是什么？"
        ),
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP2,
        "gold_pages": (6,),
        "kind": "numeric_example",
        "reference_facts": (
            "X 与 Y 的一个最长公共子序列是 B C B A",
            "B D A B 与 B C A B 也是 X 和 Y 的最长公共子序列",
        ),
    },
    {
        "id": "dp2-q03",
        "question": "LCS 动态规划中 c[i,j] 表示什么？它的递归关系式是什么？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP2,
        "gold_pages": (23,),
        "kind": "equation",
        "reference_facts": (
            "c[i,j] 记录序列 Xi 和 Yj 的最长公共子序列的长度，c[i,j]=|LCS(Xi,Yj)|",
            "当 i=0 或 j=0 时 c[i,j]=0",
            "当 xi=yj 时 c[i,j]=c[i-1,j-1]+1；当 xi≠yj 时 c[i,j]=max(c[i-1,j], c[i,j-1])",
            "原问题为 c[m,n]=|LCS(X,Y)|",
        ),
    },
    {
        "id": "dp2-q04",
        "question": "LCSLength 算法求解最长公共子序列长度的时间复杂度和空间复杂度分别是多少？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP2,
        "gold_pages": (32,),
        "kind": "complexity",
        "reference_facts": (
            "算法的计算时间上界为 O(mn)",
            "算法所占用的空间显然为 O(mn)",
        ),
    },
    {
        "id": "dp2-q05",
        "question": "LCS 动态规划算法中 b 表的三种箭头“↖、↑、←”分别代表什么含义？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP2,
        "gold_pages": (29,),
        "kind": "algorithm_steps",
        "reference_facts": (
            "xi=yj 时 c[i,j]=c[i-1,j-1]+1，b[i,j] 记为“↖”",
            "c[i-1,j]≥c[i,j-1] 时 c[i,j]=c[i-1,j]，b[i,j] 记为“↑”",
            "否则 c[i,j]=c[i,j-1]，b[i,j] 记为“←”",
            "用表 b[1..m,1..n] 可以构造最优解（LCS 本身）",
        ),
    },
    {
        "id": "dp2-q06",
        "question": "如何改进 LCS 算法以减少空间开销？如果只求 LCS 的长度，最少需要多少空间？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP2,
        "gold_pages": (35,),
        "kind": "algorithm_steps",
        "reference_facts": (
            ("重构 LCS 时可以不使用 b 表：每个 c[i,j] 只依赖 c[i-1,j-1]、c[i-1,j]、c[i,j-1]，"
            "给定 c[i,j] 的值可用 O(1) 时间确定是哪些值计算得到"),
            "去掉 b 表可节省 Θ(mn) 的空间开销，但表 c 仍需要 Θ(mn) 存储空间，空间开销没有渐近减少",
            ("每次计算 c[i,j] 只需表 c 的两行（正在计算的行和上一行）；若只求 LCS 长度，"
            "甚至可以仅使用比表 c 的一行稍多一点的空间"),
        ),
    },
    {
        "id": "dp2-q07",
        "question": "穷举法（brute-force）求解最长公共子序列问题的时间复杂度是多少？为什么不可行？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP2,
        "gold_pages": (10,),
        "kind": "complexity",
        "reference_facts": (
            "穷举法列举出 X 的所有子序列，逐项核查它们是否为 Y 的子序列",
            "检查每个子序列的时间为 O(n)，X 共有 2^m 个子序列",
            "最坏情况运行时间为 O(n·2^m)，是指数运算时间，序列较大时实际不可行",
        ),
    },
    # ------------------------------------------------------------------ DP3
    {
        "id": "dp3-q01",
        "question": "0-1 背包问题的定义是什么？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP3,
        "gold_pages": (4,),
        "kind": "definition",
        "reference_facts": (
            "给定 n 种物品和一个背包，物品 i 的重量是 w_i、价值是 v_i，背包容量为 C",
            "每种物品要么装入（1），要么不装入（0），不能装入多次，也不能装入部分",
            "目标是选择装入背包的物品，使装入背包中物品的总价值最大",
        ),
    },
    {
        "id": "dp3-q02",
        "question": (
            "背包容量 C=10，三件物品的重量和价值分别为 (3,4)、(4,5)、(5,6)，"
            "0-1 背包的最优解和最大总价值是什么？"
        ),
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP3,
        "gold_pages": (4,),
        "kind": "numeric_example",
        "reference_facts": (
            "应选物品 2 和物品 3，即解 (0,1,1)",
            "总重量 w2+w3=9<10，总价值 v2+v3=11，是最大总价值",
        ),
    },
    {
        "id": "dp3-q03",
        "question": "0-1 背包问题中 m(i,j) 的递归关系式和边界条件是什么？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP3,
        "gold_pages": (12,),
        "kind": "equation",
        "reference_facts": (
            "m(i,j) 表示可选物品为 i,i+1,...,n、背包容量为 j 时问题的最优值",
            ("当 j≥w_i 时，m(i,j)=max{m(i+1,j), m(i+1,j-w_i)+v_i}；当 0≤j<w_i 时，"
            "m(i,j)=m(i+1,j)"),
            "边界条件：m(n,j)=v_n（j≥w_n）；m(n,j)=0（0≤j<w_n）",
            "通过 m(i+1,x) 来计算 m(i,x)，i 之前的物品都已完成选择",
        ),
    },
    {
        "id": "dp3-q04",
        "question": "用二维表格求解 0-1 背包问题时，算法的时间复杂度和空间复杂度分别是多少？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP3,
        "gold_pages": (16,),
        "kind": "complexity",
        "reference_facts": (
            "表格有 nC 项，每一项由其他两项在常数时间内计算得到，算法需要 O(nC) 计算时间",
            "回推构造最优解需要 O(n) 计算时间",
            "空间复杂度为 O(nC)（n 个物品，C 最大容量）",
        ),
    },
    {
        "id": "dp3-q05",
        "question": "0-1 背包问题的跳跃点算法中，受控点（控制点）是如何定义的？它有什么意义？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP3,
        "gold_pages": (21,),
        "kind": "algorithm_steps",
        "reference_facts": (
            ("设 (a,b) 和 (c,d) 是 p[i+1]∪q[i+1] 中的 2 个跳跃点，当 c≥a 且 d<b 时，(c,d) 受控于 "
            "(a,b)，从而 (c,d) 不是 p[i] 中的跳跃点"),
            "意义：装载量多、价值却少，肯定不是最优解",
            "跳跃点用 (容量, 最优值) 表示，即 (j, m(i,j))",
        ),
    },
    {
        "id": "dp3-q06",
        "question": "凸多边形最优三角剖分问题中，最优子结构性质的内容是什么？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP3,
        "gold_pages": (35,),
        "kind": "figure",
        "reference_facts": (
            ("若凸(n+1)边形 P={v0,v1,...,vn} 的最优三角剖分 T 包含三角形 v0vkvn（1≤k≤n-1），"
            "则 T 的权为三部分权之和：三角形 v0vkvn 的权，子多边形 {v0,...,vk} 和 {vk,...,vn} 的权之和"),
            "W(T)=W({v0,...,vk})+W({vk,...,vn})+W(v0vkvn)",
            "由 T 确定的这 2 个子多边形的三角剖分也是最优的（否则 T 不是最优三角剖分，矛盾）",
        ),
    },
    {
        "id": "dp3-q07",
        "question": "凸多边形最优三角剖分中，t[i][j] 是如何定义的？原问题的最优值和子问题个数分别是什么？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP3,
        "gold_pages": (36,),
        "kind": "equation",
        "reference_facts": (
            "t[i][j] (1≤i<j≤n) 为凸子多边形 {vi-1,vi,...,vj} 的最优三角剖分所对应的权函数值（最优值）",
            "为方便起见，设退化的多边形 {vi-1,vi} 具有权值 0",
            "要计算的凸(n+1)边形 P 的最优权值为 t[1][n]",
            "子问题个数为 Θ(n^2)",
        ),
    },
    # ------------------------------------------------------------------ DP4
    {
        "id": "dp4-q01",
        "question": "最优二叉搜索树问题中，为什么要引入虚拟键 d0,d1,...,dn？它们满足什么大小关系？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP4,
        "gold_pages": (14,),
        "kind": "definition",
        "reference_facts": (
            ("给定有序集 S=<k1,k2,...,kn>，对每个 key ki 建立内结点；另建立 n+1 个虚拟键 "
            "d0,d1,...,dn，搜索概率为 qi，每个 di 对应建立一个叶子结点（对应不在 S 中的值）"),
            "d0 表示该值 < k1，dn 表示该值 > kn",
            "1≤i≤n-1 时，ki < di < ki+1",
        ),
    },
    {
        "id": "dp4-q02",
        "question": "建立二叉搜索树与快速排序有什么联系？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP4,
        "gold_pages": (16,),
        "kind": "figure",
        "reference_facts": (
            ("可以用快排方式建立二叉搜索树：递归调用 QuickSort(S)，把第一个元素作为根，"
            "比它小的放左子树、大的放右子树"),
            "在随机的情况下，二叉搜索树的平均查找长度和 log n 是等数量级的",
            "插入节点的关键：递归调用快排 QuickSort(S)",
        ),
    },
    {
        "id": "dp4-q03",
        "question": "二叉搜索树的一次搜索期望代价（平均路长）计算公式是什么？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP4,
        "gold_pages": (18,),
        "kind": "equation",
        "reference_facts": (
            "在给定 BST 内的一次搜索的期望代价 = 需比较的结点个数平均值",
            "搜索成功的代价为 depth(k_i)+1，搜索不成功的代价为 depth(d_i)+1",
            "E[search cost in T] = Σ_{i=1..n} (depth_T(k_i)+1)·p_i + Σ_{i=0..n} (depth_T(d_i)+1)·q_i",
            "其中 depth_T() 表示一个节点在树 T 中的深度",
        ),
    },
    {
        "id": "dp4-q04",
        "question": "最优二叉搜索树问题中，e[i,j] 的递归公式和 root[i,j] 的作用是什么？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP4,
        "gold_pages": (34,),
        "kind": "equation",
        "reference_facts": (
            "e[i,j] 是最优 BST 的期望代价（平均搜索路长），当 i>j 时 e[i,i-1]=q_{i-1}",
            "e[i,j] = min over i≤r≤j { e[i,r-1] + e[r+1,j] + w[i,j] }",
            "root[i,j] (1≤i≤j≤n) 保存索引 r，即包含键值 ki,...,kj 的最优 BST 的根 kr",
        ),
    },
    {
        "id": "dp4-q05",
        "question": "OPTIMAL-BST 算法的时间复杂度是多少？为什么？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP4,
        "gold_pages": (40,),
        "kind": "complexity",
        "reference_facts": (
            "OPTIMAL-BST 的运行时间为 Θ(n^3)",
            "O(n^3)：三层嵌套循环，每层循环最多执行 n 次",
            "Ω(n^3)：OPTIMAL-BST(p,q,n) 的三层循环（l、i、r）下界同样是 n^3",
        ),
    },
    {
        "id": "dp4-q06",
        "question": "最优二叉搜索树中，如何利用 root 表构造出最优解（整棵树）？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_DP4,
        "gold_pages": (41,),
        "kind": "algorithm_steps",
        "reference_facts": (
            "root(i,j) 保存最优 T(i,j) 的根节点元素",
            "root(1,n) 为所求 BST 的根节点元素",
            "左子树 T(1,root(1,n)-1) 的根为 root(1,root(1,n)-1)",
            "右子树 T(root(1,n)+1,n) 的根为 root(root(1,n)+1,n)",
        ),
    },
    # --------------------------------------------------------------- Greedy
    {
        "id": "greedy-q01",
        "question": "贪心算法求解的问题一般具有哪两个重要性质？分别是什么含义？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_GREEDY,
        "gold_pages": (14,),
        "kind": "definition",
        "reference_facts": (
            "贪心算法求解的问题一般具有 2 个重要的性质：最优子结构性质和贪心选择性质",
            "最优子结构性质：每个大问题的最优解里面包括下一级子问题的最优解",
            ("贪心选择性质：问题的整体最优解可以通过一系列局部最优的贪心选择来达到，"
            "每个小问题可由贪心选择获得"),
        ),
    },
    {
        "id": "greedy-q02",
        "question": "为什么 0-1 背包问题不能用贪心算法求得最优解，而分数背包问题可以？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_GREEDY,
        "gold_pages": (16,),
        "kind": "comparison",
        "reference_facts": (
            "0-1 背包问题和分数背包问题都具有最优子结构性质",
            "分数背包问题具有贪心选择性质，而 0-1 背包问题没有这个性质",
            ("可用贪心方法时，动态规划方法可能不适用（分数背包）；可用动态规划方法时，"
            "贪心方法可能不适用（0-1 背包问题）"),
        ),
    },
    {
        "id": "greedy-q03",
        "question": (
            "背包容量 C=50，三个物品重量为 (10,20,30)、价值为 (60,100,120)，"
            "动态规划法与贪心法的选取方案和总价值分别是多少？"
        ),
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_GREEDY,
        "gold_pages": (9,),
        "kind": "numeric_example",
        "reference_facts": (
            "动态规划法：取物品 2 和 3，取法为 (0,1,1)，总价值为 220",
            "贪心法：按单位重量价值最大依次取物品 1、2，取法为 (1,1,0)，得到总价值为 160",
            "贪心法得到的结果不是最优解",
        ),
    },
    {
        "id": "greedy-q04",
        "question": "活动安排问题的贪心算法 GreedySelector 中，活动 i 与当前活动集合相容的判断条件是什么？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_GREEDY,
        "gold_pages": (24,),
        "kind": "algorithm_steps",
        "reference_facts": (
            "各活动的起始时间和结束时间存储于数组 s 和 f 中，且按结束时间的非减序排列",
            "A 数组存储所选择的活动，j 记录最近一次加入到 A 中的活动",
            ("活动 i 与集合 A 中所有活动相容的充要条件：其开始时间 s[i] 不早于最近加入集合 A 中"
            "的活动 j 的结束时间，即 s[i] ≥ f[j]"),
        ),
    },
    {
        "id": "greedy-q05",
        "question": "活动安排问题的贪心算法在输入活动已排序和未排序时，时间复杂度分别是多少？",
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_GREEDY,
        "gold_pages": (26,),
        "kind": "complexity",
        "reference_facts": (
            "如果输入的活动已按结束时间非减序排列，算法只需 O(n) 的时间安排 n 个活动",
            "如果输入的活动未按结束时间非减序排列，算法需要 O(nlogn) 的时间重排",
        ),
    },
    {
        "id": "greedy-q06",
        "question": (
            "分治法、动态规划和贪心算法在适用类型、子问题结构、最优子结构、"
            "求解顺序和基本要素上有哪些区别？"
        ),
        "course_code": COURSE_ALGORITHMS,
        "document_id": DOC_GREEDY,
        "gold_pages": (38,),
        "kind": "table",
        "reference_facts": (
            "适用类型：分治为通用问题，动态规划和贪心为优化问题",
            "子问题结构：分治每个子问题不同，动态规划很多子问题重复，贪心只有一个子问题",
            "最优子结构：分治不要求，动态规划和贪心必须满足",
            "求解顺序：分治递归与递推都可，动态规划从底往上，贪心从顶往下",
            "基本要素：动态规划为最优子结构和重叠子问题，贪心为最优子结构和贪心选择性",
        ),
    },
    # ------------------------------------------------------------------- RNN
    {
        "id": "rnn-q01",
        "question": "循环神经网络（RNN）适合处理什么类型的数据？它的“循环”结构有什么作用？",
        "course_code": COURSE_RNN,
        "document_id": DOC_RNN,
        "gold_pages": (3,),
        "kind": "definition",
        "reference_facts": (
            "RNN 是一种专门处理序列数据的神经网络",
            ("与传统的前馈神经网络不同，RNN 具有“循环”结构，能够处理和记住前面时间步的信息，"
            "使其特别适用于时间序列数据或有时序依赖的任务"),
            "序列数据的特点：后面的数据跟前面的数据有关系",
            ("RNN 的应用包括自然语言处理（文本生成、语言建模、机器翻译、情感分析）、"
            "时间序列预测、语音识别、音乐生成"),
        ),
    },
    {
        "id": "rnn-q02",
        "question": "词嵌入层的作用是什么？它如何把 100 个词表示为 128 维向量？",
        "course_code": COURSE_RNN,
        "document_id": DOC_RNN,
        "gold_pages": (7,),
        "kind": "definition",
        "reference_facts": (
            "词嵌入层的作用就是将文本转换为向量",
            "词嵌入层在 RNN 中的作用有输入表示、降低维度和捕捉语义相似性",
            ("词嵌入层根据输入的词的数量构建一个词向量矩阵：100 个词、每个词 128 维时，"
            "矩阵形状为 100*128，输入的每个词对应矩阵中的一个向量"),
        ),
    },
    {
        "id": "rnn-q03",
        "question": "在 PyTorch 中使用 nn.Embedding 时，num_embeddings 和 embedding_dim 两个参数分别表示什么？",
        "course_code": COURSE_RNN,
        "document_id": DOC_RNN,
        "gold_pages": (9,),
        "kind": "api",
        "reference_facts": (
            "在 PyTorch 中使用 nn.Embedding 词嵌入层实现输入词的向量化",
            "num_embeddings 表示词的数量",
            "embedding_dim 表示用多少维的向量来表示每个词",
            "示例：nn.Embedding(num_embeddings=10, embedding_dim=4)",
        ),
    },
    {
        "id": "rnn-q04",
        "question": "RNN 神经元中，每个时间步的隐藏状态 h_t 是如何计算出来的？",
        "course_code": COURSE_RNN,
        "document_id": DOC_RNN,
        "gold_pages": (21,),
        "kind": "equation",
        "reference_facts": (
            "每个时间步的隐藏状态 h_t 根据当前输入 x_t 和前一时刻的隐藏状态 h_{t-1} 计算",
            "Wih 表示输入数据的权重，bih 表示输入数据的偏置",
            "Whh 表示输入隐藏状态的权重，bhh 表示输入隐藏状态的偏置",
            "最后对输出的结果使用 tanh 激活函数进行计算，得到该神经元的输出隐藏状态",
        ),
    },
    {
        "id": "rnn-q05",
        "question": "PyTorch 中送入 nn.RNN 的输入数据 x、初始隐藏状态 h0、输出 output 和 hn 的形状分别是什么？",
        "course_code": COURSE_RNN,
        "document_id": DOC_RNN,
        "gold_pages": (26,),
        "kind": "table",
        "reference_facts": (
            ("输入 x 的表示形式为 [seq_len, batch, input_size]，即[句子的长度，batch 的大小，"
            "词向量的维度]"),
            ("h0 的表示形式为 [num_layers, batch, hidden_size]，即[隐藏层的层数，batch 的大小，"
            "隐藏层 h 的维数]"),
            "输出 output 的表示形式与输入 x 类似，为 [seq_len, batch, hidden_size]",
            "hn 的表示形式与输入 h0 一样，为 [num_layers, batch, hidden_size]",
        ),
    },
    {
        "id": "rnn-q06",
        "question": "RNN 中隐藏状态 h 的作用是什么？",
        "course_code": COURSE_RNN,
        "document_id": DOC_RNN,
        "gold_pages": (17,),
        "kind": "figure",
        "reference_facts": (
            ("h 表示隐藏状态，保存了序列数据中的历史信息，并将这些信息传递给下一个时间步，"
            "从而允许 RNN 处理和预测序列数据中的元素"),
            ("每一次的输入包含两个值：上一个时间步的隐藏状态、当前状态的输入值 x；"
            "每一次的输出也会包含两个值：当前时间步的隐藏状态、当前时间步的预测结果 y"),
            ("隐藏状态的作用：记忆功能（在不同时间步之间传递信息）、上下文理解（携带过去的信息，"
            "用于理解和生成与上下文相关的输出）、连接不同时间步（通过循环连接处理变长序列）"),
        ),
    },
    {
        "id": "rnn-q07",
        "question": "文本生成案例中用于《歌词生成》的网络模型包含哪三个层，各自的作用是什么？",
        "course_code": COURSE_RNN,
        "document_id": DOC_RNN,
        "gold_pages": (41,),
        "kind": "algorithm_steps",
        "reference_facts": (
            "网络模型主要包含三个层：词嵌入层、循环网络层、全连接层",
            "词嵌入层：用于将语料转换为词向量",
            "循环网络层：提取句子语义",
            "全连接层：输出对词典中每个词的预测概率",
        ),
    },
)

__all__ = [
    "COURSEWARE_GOLDEN_QUESTIONS",
    "COURSE_ALGORITHMS",
    "COURSE_RNN",
    "DOCUMENTS",
    "DOC_DP1",
    "DOC_DP2",
    "DOC_DP3",
    "DOC_DP4",
    "DOC_GREEDY",
    "DOC_RNN",
    "gold_page_keys",
    "questions_for_course",
    "questions_for_document",
]


def gold_page_keys(question: Mapping[str, Any]) -> tuple[tuple[str, int], ...]:
    """Return the page-level gold keys ``(document_id, page)`` for a question."""
    return tuple(
        (str(question["document_id"]), int(page)) for page in question["gold_pages"]
    )


def questions_for_document(document_id: str) -> tuple[dict[str, Any], ...]:
    """Return the golden questions annotated for ``document_id``."""
    return tuple(q for q in COURSEWARE_GOLDEN_QUESTIONS if q["document_id"] == document_id)


def questions_for_course(course_code: str) -> tuple[dict[str, Any], ...]:
    """Return the golden questions whose retrieval must be filtered by ``course_code``."""
    return tuple(q for q in COURSEWARE_GOLDEN_QUESTIONS if q["course_code"] == course_code)
