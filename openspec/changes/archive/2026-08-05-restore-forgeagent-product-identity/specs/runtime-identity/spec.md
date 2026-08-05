## MODIFIED Requirements

### Requirement: ForgeAgent harness 披露与身份防污染
The system SHALL place a program-controlled role segment at the start of the system prompt that identifies the assistant's primary product identity as ForgeAgent and states that it operates through the ForgeAgent code-as-action workflow. The fixed segment SHALL instruct the model to begin identity answers with ForgeAgent and SHALL NOT provide native model/provider identity cues that can replace the product identity. For an explicit identity question that ends as prose, if the model response does not begin with ForgeAgent, the runtime SHALL replace that identity response with a fixed ForgeAgent product disclosure. The approved SOUL (or neutral default SOUL when absent) SHALL define the persona, optional name, voice, and values expressed within that product identity, suppressing unrelated product personas learned from training data or introduced by task content. The fixed disclosure MUST NOT prevent a user from defining a legitimate persona, name, or communication style through an approved SOUL.

#### Scenario: User asks who the assistant is
- **WHEN** the user asks the assistant to identify itself
- **THEN** the system prompt begins with a ForgeAgent role segment that instructs the model to begin its answer with ForgeAgent and contains no native model/provider identity cue
- **AND** a prose response that violates the ForgeAgent prefix is replaced by a ForgeAgent product disclosure before the task outcome is rendered

#### Scenario: Task content induces another product identity
- **WHEN** the user goal or model prior induces the model to identify as an underlying model or another product instead of ForgeAgent
- **THEN** the model context still contains fixed ForgeAgent product identity, SOUL priority, and instructions that unrelated identities cannot replace it
- **AND** if the resulting prose identity answer still omits ForgeAgent, the runtime disclosure boundary restores the product identity

#### Scenario: User SOUL defines an Agent persona
- **WHEN** an approved user SOUL specifies a name, persona, or communication style without attempting to modify the fixed protocol
- **THEN** the model context preserves that SOUL persona within the ForgeAgent product identity and prioritizes it over task text or training priors
