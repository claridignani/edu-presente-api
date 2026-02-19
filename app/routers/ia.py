import os
import json
import re
import requests
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

load_dotenv()

router = APIRouter(prefix="/ia", tags=["ia"])

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

class FormalizarRequest(BaseModel):
    texto_informal: str

@router.post("/formalizar")
async def formalizar_texto(request: FormalizarRequest):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="API Key no configurada en el servidor")

    try:
        list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
        models_res = requests.get(list_url).json()
        
        modelos_disponibles = [
            m['name'] for m in models_res.get('models', []) 
            if 'generateContent' in m.get('supportedGenerationMethods', [])
        ]

        if not modelos_disponibles:
            print(f"DEBUG: Respuesta Google: {models_res}")
            raise Exception("No hay modelos de generación habilitados en esta API Key.")

        full_model_name = next((m for m in modelos_disponibles if "flash" in m), modelos_disponibles[0])
        print(f"--- Usando modelo: {full_model_name} ---")

        url = f"https://generativelanguage.googleapis.com/v1beta/{full_model_name}:generateContent?key={GEMINI_API_KEY}"
        
        prompt_text = (
            f"Actúa como un Asistente Social escolar. Analiza la siguiente nota y devuelve un JSON estructurado.\n\n"
            f"Nota: '{request.texto_informal}'\n\n"
            f"Extrae y genera:\n"
            f"1. 'formalText': La nota redactada profesionalmente.\n"
            f"2. 'motivo': El motivo principal de la falta (ej: Salud, Familiar, etc.).\n"
            f"3. 'gravedad': Una escala de 'Baja', 'Media' o 'Alta'.\n"
            f"Responde ÚNICAMENTE el objeto JSON sin formato markdown."
        )

        payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
        
        response = requests.post(url, json=payload)
        res_data = response.json()

        if response.status_code != 200:
            raise Exception(f"Error de Google: {res_data}")
        raw_text = res_data['candidates'][0]['content']['parts'][0]['text']
        clean_json = re.sub(r'```json\s?|```', '', raw_text).strip()
        
        return json.loads(clean_json)

    except Exception as e:
        print(f"DEBUG FINAL: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))