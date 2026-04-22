import chromadb
from chromadb.utils import embedding_functions
import json

def create_test_db():
    client = chromadb.PersistentClient(path="./chroma_db")
    
    embedding_func = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )
    
    collection = client.get_or_create_collection(
        name="vw_golf_mk7",
        embedding_function=embedding_func
    )
    
    # Define some dummy chunks for testing
    chunks = [
        # Tier 1 - Exact Match (EA211, Belt, 2016)
        {
            "id": "chunk_1",
            "text": "The 1.4 TSI EA211 engine in the Golf 7 uses a timing belt. It is generally very reliable, but watch out for coolant leaks from the water pump around 80,000 km.",
            "metadata": {
                "engine_family": "EA211",
                "engine_common_names": "1.4_TSI",
                "fuel_type": "petrol",
                "timing_drive": "belt",
                "years": [2014, 2015, 2016, 2017],
                "onset_km": 80000,
                "is_flagged": False
            }
        },
        # Exact Match - Component (DQ200 Transmission)
        {
            "id": "chunk_2",
            "text": "The DQ200 7-speed DSG transmission is common in the 1.4 TSI. Owners report juddering in low gears, usually due to worn clutches.",
            "metadata": {
                "transmission": "DQ200",
                "is_flagged": False,
                "engine_common_names": "1.4_TSI,1.2_TSI",
                "engine_family": "EA211", # Inherited from video title context
                "fuel_type": "petrol",      # Inherited
                "timing_drive": "belt"      # Inherited
            }
        },
        # Tier 4 - General Model Issues (MK7)
        {
            "id": "chunk_3",
            "text": "Common issues with the VW Golf MK7 include infotainment screen glitches and water ingress in the spare wheel well.",
            "metadata": {
                "model": "golf_mk7",
                "is_flagged": False,
                "engine_family": "EA211", # General issues are usually tagged with main families
                "fuel_type": "petrol",
                "timing_drive": "belt",
                "years": [2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020]
            }
        },
        # WRONG - Should be EXCLUDED (Chain-driven EA111)
        {
            "id": "chunk_4",
            "text": "The 1.4 TSI with a timing chain often suffers from chain stretch and tensioner failure, causing rattle on cold starts.",
            "metadata": {
                "engine_family": "EA111",
                "timing_drive": "chain",
                "is_flagged": False
            }
        },
        # WRONG - Should be EXCLUDED (Diesel EA288)
        {
            "id": "chunk_5",
            "text": "The 1.6 TDI diesel is very fuel efficient but has problems with the DPF if driven only in the city.",
            "metadata": {
                "engine_family": "EA288",
                "fuel_type": "diesel",
                "is_flagged": False
            }
        },
        # WRONG - Should be EXCLUDED (DQ250 Wet-Clutch DSG)
        {
            "id": "chunk_6",
            "text": "The 6-speed DQ250 wet-clutch DSG is very robust but needs oil changes every 60,000 km.",
            "metadata": {
                "transmission": "DQ250",
                "is_flagged": False
            }
        }
    ]
    
    # Add to collection
    collection.add(
        ids=[c['id'] for c in chunks],
        documents=[c['text'] for c in chunks],
        metadatas=[c['metadata'] for c in chunks]
    )
    
    print("Test ChromaDB created with 6 chunks.")

if __name__ == "__main__":
    create_test_db()
