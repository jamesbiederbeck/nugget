Here are the three proposals from the product-manager review:                                                                                                                                                   
                                                                                                                                                                                                                  
  ---                                                                                                                                                                                                             
  1. http_fetch — Retrieve a URL's body (text or JSON)                                                                                                                                                            
                                                                                                                                                                                                                  
  Inputs: url, method, headers, body, max_chars, as_json                                                                                                                                                          
  Returns: { status, url, headers, content, truncated }                                                                                                                                                           
                                                                                                                                                                                                                  
  Rationale: Closes the most common reason a user reaches for shell today. No new dependencies (Wallabag already pulls HTTP). Composes naturally with $var output routing. Approval gate: ask by default,         
  config-overridable to allow for safe domains.                                                                                                                                                                   
                                                                                                                                                                                                                  
  ---                                                                                                                                                                                                             
  2. jq — JMESPath query over JSON                                                                                                                                                                                
                                                                                                                                                                                                                  
  Inputs: data (string or $var dict), query
  Returns: { result, query }                                                                                                                                                                                      
                  
  Rationale: JMESPath is already a dependency — render_output uses it internally. This just exposes the same engine as a tool step. Pure and deterministic → allow gate. Pairs well with http_fetch: fetch a large
   API response, then slice it before display.
                                                                                                                                                                                                                  
  ---             
  3. tasks — Lightweight persistent todo list (SQLite)
                                                                                                                                                                                                                  
  Operations: add, list, complete, delete, update
  Returns structured task records with id, text, status, tag, created_at                                                                                                                                          
                                                                                                                                                                                                                  
  Rationale: Mirrors memory.py's design exactly (same SQLite pattern, same operation switch, ask on delete / allow otherwise). Gives the model a structured planning surface across sessions — currently users    
  fake this by stuffing checkbox markdown into free-form memory keys.                                                                                                                                             
                                                                                                                                                                                                                  
  ---             
  All three are allow-by-default, remove shell escape-hatch uses, and multiply the value of render_output's $var binding system. Which of these looks worth building first?
