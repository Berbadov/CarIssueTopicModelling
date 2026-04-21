# Vector-Based Issue Extraction Architecture

This diagram illustrates the hierarchical approach used to extract car issues using ChromaDB vector stores and multi-tiered retrieval strategies.

## System Architecture Diagram

```mermaid
graph TD
    subgraph Input_Layer [Input Layer]
        Listing["Car Listing Text<br/>(e.g., '2017 Golf 1.4 TSI DSG')"]
        Parser["Listing Parser<br/>(parse_listing.py)"]
        Spec["Listing Spec<br/>(Year, Fuel, Engine, Transmission)"]
    end

    subgraph Query_Generation [Query Generation]
        BaseProbes["Base Probes<br/>(common issues, engine, electrical...)"]
        FuelProbes["Fuel-Specific Probes<br/>(Turbo, EGR, DPF, Coils...)"]
        FamilyProbes["Family Probes<br/>(EA211 engine problems, etc.)"]
        ProbeBuilder["Probe Builder<br/>(rag_answer.py)"]
    end

    subgraph Vector_Store_ChromaDB [Vector Store: ChromaDB]
        subgraph Tier_0_Component_Layer [Tier 0: Component Knowledge Layer]
            Comp_K9K["component_K9K<br/>(Cross-model Engine)"]
            Comp_EA211["component_EA211<br/>(Cross-model Engine)"]
            Comp_DQ200["component_DQ200<br/>(Cross-model Gearbox)"]
        end
        
        subgraph Car_Model_Layer [Car Model Layer]
            Slug_Golf7["vw_golf_mk7<br/>(Model Specific)"]
            Slug_Clio4["renault_clio_mk4<br/>(Model Specific)"]
        end
    end

    subgraph Retrieval_Filtering [Retrieval & Tier Filtering]
        Search["Vector Search<br/>(Multilingual-E5-Base)"]
        Tier1["Tier 1: Exact Displacement Match"]
        Tier2["Tier 2: Engine Family Match"]
        Tier3["Tier 3: Fuel Type Match"]
        Tier4["Tier 4: General Model Content"]
    end

    subgraph Issue_Extraction [Issue Extraction & Categorization]
        LLM["DeepSeek LLM<br/>(Grounded Extraction)"]
        
        subgraph Component_Hierarchy [Component Hierarchy]
            Engine["Engine Issues"]
            Trans["Transmission Issues"]
            Suspension["Suspension/Steering"]
            Electronics["Electronics/Sensors"]
            Body["Body/Interior"]
            Brakes["Braking System"]
        end
    end

    %% Connections
    Listing --> Parser
    Parser --> Spec
    Spec --> ProbeBuilder
    
    BaseProbes --> ProbeBuilder
    FuelProbes --> ProbeBuilder
    FamilyProbes --> ProbeBuilder
    
    ProbeBuilder -- "Query: {Probe}" --> Search
    
    Search -- "Retrieves from" --> Tier_0_Component_Layer
    Search -- "Retrieves from" --> Car_Model_Layer
    
    Search --> Tier1
    Tier1 --> Tier2
    Tier2 --> Tier3
    Tier3 --> Tier4
    
    Tier4 -- "Filtered Chunks" --> LLM
    
    LLM --> Engine
    LLM --> Trans
    LLM --> Suspension
    LLM --> Electronics
    LLM --> Body
    LLM --> Brakes

    Engine --- IssueE1["Carbon Buildup"]
    Engine --- IssueE2["Turbo Failure"]
    Trans --- IssueT1["DSG Mechatronic"]
    Suspension --- IssueS1["Bushings Wear"]
```

## Key Components of the Approach

1.  **Listing Specification (`ListingSpec`)**: The system first translates a raw ad into a structured specification (year, fuel, engine code).
2.  **Neutral Probing**: Instead of searching for "broken DSG", the system uses neutral probes like "transmission problems" or "{engine_code} engine experience" to avoid bias and discover unknown issues.
3.  **Multi-Tiered ChromaDB**:
    *   **Component Layer (Tier 0)**: Contains specialized knowledge about specific engines (like the K9K) or transmissions (like DQ200) regardless of the car model they are in.
    *   **Car-Level Layer**: Contains model-specific transcripts and forum discussions.
4.  **Graceful Relaxation (Tiers 1-4)**: The system first tries to find evidence matching the exact engine. if not enough evidence is found, it relaxes the filter to the engine family, then fuel type, and finally general model content.
5.  **Component-Centric Output**: The final extraction groups issues into logical automotive components (Engine, Transmission, Suspension, etc.), providing a clear "lemon" risk assessment for the user.
