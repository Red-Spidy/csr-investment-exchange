"""Prompt text for proposal extraction.

Kept in its own module and versioned. PROMPT_VERSION is written to every
project_extractions row, so any stored extraction can be traced back to the
exact prompt that produced it. Bump it whenever SYSTEM_PROMPT changes.
"""

PROMPT_VERSION = "v1"

SYSTEM_PROMPT = """You extract structured data from Indian NGO project proposals \
submitted for CSR funding under Section 135 of the Companies Act.

Your output feeds an automated funding pipeline: an impact-prediction model reads \
your numbers, and a composite risk grade decides whether the project is approved \
or routed to human review. Treat accuracy as more important than completeness.

RULES

1. Emit null for anything the proposal does not state. Never infer, estimate, \
round, or carry a number over from a similar project. A field you are unsure \
about must be null. This is the single most important rule: a fabricated \
beneficiary count or baseline propagates into a real funding decision.

2. Quote the proposal's own framing for goals. Do not editorialise, do not add \
goals the proposal implies but does not state.

3. For SDGs, assign only goals the project genuinely addresses through its stated \
activities, not goals it gestures at. An education project that happens to feed \
children addresses SDG 4 and SDG 2; an education project that merely mentions \
poverty in its motivation does not address SDG 1. Give each assigned SDG a \
calibrated confidence between 0 and 1 - use the full range, and reserve values \
above 0.9 for cases where the activities map unambiguously.

4. red_flags records concerns visible in the text itself: absent budget detail, \
unverifiable or unusually strong claims, a cost per beneficiary that looks \
implausible for the sector, internally inconsistent numbers. Leave it empty when \
the proposal is unremarkable. Do not speculate about the NGO's honesty or intent \
- you are flagging text for a human reviewer, not making an accusation.

5. Money is in Indian rupees. "50 lakh" is 5,000,000 and "2 crore" is 20,000,000. \
Convert to a plain number, but only when the proposal states the figure."""

USER_TEMPLATE = """Extract structured data from this NGO project proposal.

<title>{title}</title>
<sector>{sector}</sector>
<proposal>
{proposal_text}
</proposal>"""

# Few-shot examples sit between the system prompt and the proposal. They are
# byte-identical across every call, which is what makes the cached prefix work.
FEW_SHOT: list[dict] = [
    {
        "role": "user",
        "content": USER_TEMPLATE.format(
            title="Clean water access, Jaisalmer",
            sector="water_sanitation",
            proposal_text=(
                "Jal Seva proposes to repair 180 handpumps across 45 villages in "
                "Jaisalmer district over 10 months. Waterborne disease incidence in "
                "these villages currently sits at 18% and we aim to bring it to 12%. "
                "The programme reaches roughly 26,000 residents. Budget: 15 lakh, of "
                "which 9 lakh is parts and labour and 3 lakh is chlorination supplies."
            ),
        ),
    },
    {
        "role": "assistant",
        "content": (
            '{"goals":["repair 180 handpumps across 45 villages",'
            '"reduce waterborne disease incidence"],'
            '"target_metric":{"name":"disease_incidence","unit":"percent_reduction",'
            '"baseline":18.0,"target":12.0},'
            '"beneficiaries":{"count":26000,"group":"village residents"},'
            '"geography":{"state":"Rajasthan","district":"Jaisalmer","rural_urban":"rural"},'
            '"budget_lines":[{"item":"parts and labour","amount":900000.0},'
            '{"item":"chlorination supplies","amount":300000.0}],'
            '"duration_months":10,"sdgs":[6,3],'
            '"sdg_confidence":{"6":0.97,"3":0.68},"red_flags":[]}'
        ),
    },
    {
        "role": "user",
        "content": USER_TEMPLATE.format(
            title="Library expansion programme",
            sector="education",
            proposal_text=(
                "We want to add reading rooms to 12 schools in Rajasthan and buy books. "
                "This will help children learn better. We request 9 lakh."
            ),
        ),
    },
    {
        "role": "assistant",
        # The point of this example: almost everything is genuinely absent, so
        # almost everything is null. This is what teaches the model to abstain.
        "content": (
            '{"goals":["add reading rooms to 12 schools","purchase books"],'
            '"target_metric":null,'
            '"beneficiaries":{"count":null,"group":"school children"},'
            '"geography":{"state":"Rajasthan","district":null,"rural_urban":null},'
            '"budget_lines":[],"duration_months":null,"sdgs":[4],'
            '"sdg_confidence":{"4":0.74},'
            '"red_flags":["no budget breakdown provided for the requested 9 lakh",'
            '"no measurable outcome or baseline stated"]}'
        ),
    },
]
