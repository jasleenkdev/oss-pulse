{# True for automation accounts: the [bot] suffix or a login listed in the seed. #}
{% macro is_bot(login) %}
  (
    {{ login }} like '%[bot]'
    or lower({{ login }}) in (select lower(login) from {{ ref('known_bots') }})
  )
{% endmacro %}

{# Punctuation-free key that folds "good-first-issue", "Good First Issue" and emoji prefixes. #}
{% macro label_key(label) %}
  trim(regexp_replace(lower({{ label }}), '[^a-z0-9]+', ' ', 'g'))
{% endmacro %}

{% macro hours_between(start_ts, end_ts) %}
  (epoch({{ end_ts }}) - epoch({{ start_ts }})) / 3600.0
{% endmacro %}
