{# Flat list matching CHANGELOG.md: "- {Type}: {text}", no category headings. #}
{%- for section, _ in sections.items() -%}
{%- if sections[section] -%}
{%- for category, val in definitions.items() if category in sections[section] -%}
{%- for text, values in sections[section][category].items() %}
- {{ definitions[category]["name"] }}: {{ text }}
{% endfor -%}
{%- endfor -%}
{%- endif -%}
{%- endfor -%}
{{ "\n" }}
