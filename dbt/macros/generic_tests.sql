{% test non_negative(model, column_name) %}
  select * from {{ model }} where {{ column_name }} < 0
{% endtest %}

{% test between(model, column_name, low, high) %}
  select * from {{ model }} where {{ column_name }} < {{ low }} or {{ column_name }} > {{ high }}
{% endtest %}

{% test not_before(model, column_name, other_column) %}
  select * from {{ model }} where {{ column_name }} < {{ other_column }}
{% endtest %}
