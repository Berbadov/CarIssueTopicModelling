Car Issue Topic Modeling

[Classic usage guide for vectorApproach, with data gathering approaches]

[VectorApproach architecture graph]


VectorApproach is the cost and computing minimised approach with almost or more performing than legacy experiments.

---------
[STM forum data results]


---------
[BERTopic forum data results]


--------
[Youtube transcript llm classificiation and extraction data results]


--------


Story:
Initially, I hypothesized that gathering forum messages and applying topic modeling would effectively aggregate the primary issues of a specific car. I started with the VW Golf 7 due to its diverse engine and transmission configurations—specifically, the various TSI engine revisions and the DQ200 vs. DQ250 gearboxes, which present significant reliability contrasts. My first data source was a local Turkish Golf forum. I cleaned the scraped, anonymous messages using regex, filtering for issue-related keywords, which reduced the noise by 60%.

At first, I structured the messages at an atomic level but soon realized it was better to classify them by topic during the scraping stage to retain context. After regex filtering, I secured a decent dataset, albeit with some Type II errors (false negatives). While a classification algorithm would have been useful here, I skipped it to avoid computational overhead, planning to rely entirely on Structural Topic Modeling (STM) and BERTopic for the heavy lifting.

STM performed surprisingly well after stopword removal, despite long compute times on small data. However, it struggled with granular technical distinctions, like differentiating between timing belts and chains. To automate readability, I passed these topics and their contexts via API to DeepSeek-V3. Unfortunately, attempting to force the model to capture those micro-distinctions only degraded its overall performance.

I then tested BERTopic, which proved challenging with the Turkish language due to extensive text-preprocessing requirements. It underperformed compared to STM, likely due to suboptimal tuning on my end.

I eventually realized the root issue was the source data itself. Users describe car problems colloquially, creating severe linguistic ambiguity. For example, a user might just say, "My 2015 Golf makes this noise," omitting the engine code or production month, assuming the forum context is enough. (Bridging this gap between verbal explanations and technical faults is a research question in its own right).

Before pivoting, I tested a UK-based forum. However, the data skewed heavily toward enthusiast models like the GTI, GTD, and Golf R. While issue extraction was still possible, it didn't represent the standard commuter car market. Nevertheless, I don’t believe I utilized STM and BERTopic to their absolute full potential.

Despite these hurdles, topic modeling successfully unearthed critical, niche user-experience details—such as the AFS (Advanced Front-lighting System) cornering bulb failures in Golf models. Interestingly, this specific flaw never surfaced in my later YouTube transcript analysis.

I also explored official databases like the NHTSA, but they lean heavily toward formal consumer reports and recalls. Furthermore, the data was less applicable since hatchbacks are relatively unpopular in the US market.

Recognizing that users heavily document their car experiences on video, I shifted my focus to YouTube transcripts using vectorization and RAG (Retrieval-Augmented Generation). I found it to be an excellent way to extract atomic, semantic knowledge from unstructured data. I utilized regex to flag issues and improve retrieval accuracy.

However, flagging became complex, requiring manual .yaml scaffolds to map meta-tags like engine revisions, transmission types, and trim features (e.g., sunroofs). While third-party automotive APIs could automate this, they are prohibitively expensive. Parsing Wikipedia is another option, but structuring its semantic data remains challenging. Maintaining these scaffolds without LLM intervention at some layer is difficult. Relying entirely on LLMs to structure massive datasets occasionally triggers hallucinations—your guess was actually correct: this is a known artifact of KV cache limits and context-window degradation during heavy processing.