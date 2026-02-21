
"""
Servicio de Inteligencia Artificial (LLM)
Gestión de modelos cognitivos (Ollama, Gemini) y prompts para generación de reportes clínicos.
Protege la privacidad al integrar el anonimizador en el flujo de nube.
"""
import os
import json
import threading
import time
import re
from backend.anonymizer import SessionAnonymizer

class IntelligenceService:
    def __init__(self):
        self.anonymizer = SessionAnonymizer()
    
    def process_ollama(self, transcript: str, model_name: str, transcribe_duration: float) -> dict:
        """
        Process transcript with local Ollama model (FREE tier).
        No anonymization needed - all data stays local.
        Generates only nota_clinica (simple paragraph summary).
        """
        import ollama
        system_prompt = (
            "Eres un asistente psicológico experto. Tu tarea es redactar una nota de evolución clínica en un ÚNICO PÁRRAFO de PROSA CONTINUA (texto fluido).\n"
            "REGLAS OBLIGATORIAS:\n"
            "- Redacta en TERCERA PERSONA y TIEMPO PASADO.\n"
            "- NO uses formato JSON, llaves {}, corchetes [] ni comillas dentro del texto narrativo.\n"
            "- NO uses listas, viñetas, negritas ni markdown.\n"
            "- Sigue este esquema: [Estado emocional] + [Conflicto central] + [Intervención] + [Conclusión/Tarea].\n"
            "\n"
            "Responde EXCLUSIVAMENTE con un objeto JSON válido con la clave 'nota_clinica':\n"
            '{"nota_clinica": "El paciente se presentó..."}'
        )
        
        user_prompt = (
            f"Transcripción de la sesión:\n{transcript}\n\n"
            "Genera la nota clínica en JSON ahora:"
        )
        
        try:
            start_gen = time.time()
            print(f"[OLLAMA] Generando nota clínica FREE con {model_name}...")
            response = ollama.generate(
                model=model_name, 
                system=system_prompt, 
                prompt=user_prompt, 
                format='json', 
                options={
                    'temperature': 0.2,
                    'num_ctx': 4096,
                    'num_predict': 512,  # Reduced - only need a paragraph
                    'top_k': 20,
                    'top_p': 0.9
                } 
            )
            gen_duration = round(time.time() - start_gen, 2)
            
            response_text = response.get('response', '')
            
            try:
                # Robust extraction for "Thinking" models and formatted output
                # 1. Remove <think> blocks (reasoning chains)
                clean_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL)
                
                # 2. Extract JSON object (find first { and last }) to ignore conversational prefixes/suffixes
                json_match = re.search(r'(\{.*\})', clean_text, re.DOTALL)
                if json_match:
                    clean_text = json_match.group(1)
                
                # 3. Clean residual markdown
                clean_text = re.sub(r'```(?:json)?', '', clean_text).replace('```', '').strip()
                
                data = json.loads(clean_text)

                # Add metrics
                data["_metrics"] = {
                    "transcription_time": transcribe_duration,
                    "generation_time": gen_duration,
                    "total_time": round(transcribe_duration + gen_duration, 2),
                    "device": "cpu"
                }
                data["_model_file"] = model_name
                data["_provider"] = "ollama"
                return data, None
                
            except Exception as e:
                print(f"JSON Parse failed: {e}. Falling back to raw text.")
                return {
                    "nota_clinica": response_text, 
                    "_warning": "Formato no estructurado (JSON fallido)",
                    "_raw": response_text,
                    "_provider": "ollama"
                }, None
        except Exception as e:
            return {"error": f"Ollama Error: {str(e)}"}, None

    def process_gemini(self, transcript: str, transcribe_duration: float, patient_context: str = None) -> tuple:
        """
        Process transcript with Gemini API (cloud).
        Uses anonymization to protect sensitive data before sending to cloud.
        
        Args:
            transcript: The full text to process.
            transcribe_duration: Time taken for transcription (for metrics).
            patient_context: Patient name to prioritize in anonymization.
            
        Returns:
            tuple: (final_json: dict, secret_map: dict)
        """
        from google import genai
        from google.genai import types
        try:
            # 1. Anonymize locally
            known_context = [patient_context] if patient_context else None
            anonymized_text = self.anonymizer.anonymize(transcript, known_context=known_context)
            secret_map = self.anonymizer.get_secret_map()
            
            # 2. Send to Gemini
            api_key = os.getenv("GEMINI_API_KEY")
            client = genai.Client(api_key=api_key)
            model_id = 'gemini-3-flash-preview'

            system_instructions = (
                "Eres un asistente psicológico clínico experto observando una sesión de terapia.\n"
                "Tu objetivo es generar un reporte clínico completo y estructurado.\n\n"
                "DIRECTRICES DE FORMATO JSON:\n"
                "Responde ÚNICAMENTE con un objeto JSON válido con la siguiente estructura anidada:\n"
                "{\n"
                "  'clinico': {\n"
                "    'subjetivo': 'Síntomas y reporte verbal del paciente (S).',\n"
                "    'objetivo': 'Observaciones de conducta, afecto y apariencia (O).',\n"
                "    'analisis': 'Interpretación clínica e hipótesis (A).',\n"
                "    'plan': 'Acuerdos y tareas (P).',\n"
                "    'riesgos': ['Riesgo 1', 'Riesgo 2']\n"
                "  },\n"
                "  'paciente': {\n"
                "    'puntos_clave': ['Insight clave 1', 'Logro importante 2'],\n"
                "    'tarea_semana': 'Una tarea terapéutica concreta'\n"
                "  },\n"
                "  'sentimiento': 'Estado emocional (ej: Ansioso, Esperanzado)',\n"
                "  'sugerencias_ia': ['Sugerencia clínica 1', 'Recomendación 2']\n"
                "}\n\n"
                "MANEJO DE DATOS ANONIMIZADOS:\n"
                "1. El texto de entrada está anonimizado y contiene etiquetas (ej. [PER_n], [LOC_n]).\n"
                "2. NO DEVUELVAS los placeholders en tu respuesta (ej. no escribas '[PER_1]'). Redacta basándote en el contexto general y clínico.\n"
                "3. Usa términos descriptivos, genéricos y naturales (ej: 'el paciente', 'su pareja', 'su hermano', 'su lugar de trabajo') para mantener la fluidez del texto.\n"
                "4. NO inventes nombres anatómicos ni datos específicos, mantén el foco en la descripción clínica."
            )

            start_gen = time.time()
            response = client.models.generate_content(
                model=model_id,
                contents=f"{system_instructions}\n\nTRANSCRIPCIÓN DE LA SESIÓN:\n{anonymized_text}\n\nGenera el JSON ahora:",
                config=types.GenerateContentConfig(
                    candidate_count=1,
                    temperature=0.1,
                    response_mime_type="application/json"
                )
            )
            gen_duration = round(time.time() - start_gen, 2)
            
            response_text = response.text
            clean_text = response_text.replace("```json", "").replace("```", "").strip()
            final_json = json.loads(clean_text)
            
            # 3. Deanonymize locally
            def recursive_deanonymize(obj):
                if isinstance(obj, str):
                    return self.anonymizer.deanonymize(obj)
                elif isinstance(obj, list):
                    return [recursive_deanonymize(item) for item in obj]
                elif isinstance(obj, dict):
                    return {k: recursive_deanonymize(v) for k, v in obj.items()}
                return obj
            
            final_json = recursive_deanonymize(final_json)
            
            # Metrics
            final_json["_generation_time"] = gen_duration
            final_json["_provider"] = "gemini"
            final_json["_anonymized_transcript"] = anonymized_text
            final_json["_metrics"] = {
                "transcription_time": transcribe_duration,
                "generation_time": gen_duration,
                "total_time": round(transcribe_duration + gen_duration, 2),
                "device": "cloud-tpu"
            }
            
            return final_json, secret_map
            
        except Exception as e:
            return {"error": f"Gemini Error: {str(e)}"}, {}

