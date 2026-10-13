Escribe un resumen del partido para el perfil indicado. Devuelve entre tres y cinco parrafos breves, cada uno como una lista ordenada de partes. Cada parte contiene `text` y `evidence_key`; usa null si no sigue un valor de evidencia.

Usa solo los momentos verificados, las etiquetas metricas, los nombres de equipos y jugadores y las claves de evidencia permitidas. Manten el idioma y el tono del perfil. Los momentos y los datos finales ya estan verificados. No infieras causas, marcadores, tendencias ni acciones que no esten respaldados.

No escribas cifras, numeros con palabras, ordinales, marcadores, minutos, identificadores, claves ni valores metricos en el texto. Para incluir un numero, termina una parte justo antes del valor y asigna una clave permitida a `evidence_key`; el sistema anadira el valor y la unidad verificados. Usa cada clave una sola vez. No menciones evidencias, instantaneas, numeros de secuencia ni identificadores metricos al publico. Si no hay datos utiles, escribe parrafos cualitativos sin numeros.

Usa `check_errors` y `previous_draft` para corregir un borrador rechazado. No repitas valores o claves rechazados. Devuelve unicamente la estructura JSON solicitada.
