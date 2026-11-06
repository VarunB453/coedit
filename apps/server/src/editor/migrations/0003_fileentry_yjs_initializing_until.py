from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("editor", "0002_collaboration_access")]

    operations = [
        migrations.AddField(
            model_name="fileentry",
            name="yjs_initializing_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]