""" Miscellaneous utilities not specific to any app. """
import csv
from io import StringIO

from guardian.shortcuts import get_perms
from rest_framework.exceptions import ValidationError

from registrar.apps.api.constants import ENROLLMENT_PERMISSIONS_LIST

from .models import OrganizationGroup
from .permissions import DB_TO_API_PERMISSION_MAPPING


def get_user_organizations(user):
    """
    Get the Org Group of the user passed in.

    Returns: set[Organization]
    """
    user_groups = user.groups.all()
    user_organizations = set()
    for group in user_groups:
        try:
            user_org_group = OrganizationGroup.objects.get(id=group.id)
            user_organizations.add(user_org_group.organization)
        except OrganizationGroup.DoesNotExist:
            pass
    return user_organizations


def get_effective_user_program_api_permissions(user, program):
    """
    Returns a set of all APIPermissions granted to the user on a
    program  either in the context of a program or an organization.
    This includes permissions granted though a global permission or role.

    This will filter out APIPermissions for the program that are not valid
    for the program. Currently, this only removes a user's read and/or write
    enrollments permissions for a program that does not have enrollments enabled.
    """
    user_permissions = get_user_api_permissions(user, program).union(
        get_user_api_permissions(user, program.managing_organization))

    user_permissions = _remove_permissions_if_enrollments_disabled(program, user_permissions)

    return user_permissions


def _remove_permissions_if_enrollments_disabled(program, user_permissions):
    """
    If a program does not have enrollments enabled, remove the user's
    permissions to read or write enrollments for that program.
    """
    if not program.is_enrollment_enabled:
        return user_permissions - set(ENROLLMENT_PERMISSIONS_LIST)

    return user_permissions


def get_user_api_permissions(user, obj=None):
    """
    Returns a set of all APIPermissions granted to the user on a
    provided object instance. This includes permissions granted though a
    global permission or role. If no object is passed only global permissions
    will be returned.

    You should not use this function directly if you want a set of a user's effective
    APIPermissions, as this function does not account for programs for which enrollments
    are disabled. Use the get_effective_user_program_api_permissions function for this
    purpose instead.
    """
    user_object_permissions = get_perms(user, obj) if obj is not None else []
    user_global_permissions = list(user.get_all_permissions())

    user_api_permissions = set()

    for db_perm in user_object_permissions + user_global_permissions:
        if db_perm in DB_TO_API_PERMISSION_MAPPING:  # pragma: no branch
            user_api_permissions.add(DB_TO_API_PERMISSION_MAPPING[db_perm])

    return user_api_permissions


def serialize_to_csv(items, field_names, include_headers=False):
    """
    Serialize items into a CSV-formatted string. Column headers optional.

    Booleans are serialized as True and False
    Uses Windows-style line endings ('\r\n').
    Trailing newline is included.

    Arguments:
        items (list[dict])
        field_names (tuple[str])
        include_headers (bool)

    Returns: str
    """
    outfile = StringIO()
    writer = csv.DictWriter(
        outfile, fieldnames=field_names, extrasaction="ignore"
    )
    if include_headers:
        writer.writeheader()
    for item in items:
        writer.writerow(item)
    return outfile.getvalue()


class StrippedLowercaseFieldNamesDictReader(csv.DictReader):
    """
    Simple subclass of DictReader that ignores leading and trailing whitespace
    for field names, and converts them to lowercase.

    Uploaded CSVs are often generated by Excel, so we should expect that
    extra whitespace may be present. It is also reasonable that the
    creator of the CSV may not know that the field names are case-sensitive.

    Note that this does not affect the values of the fields themselves.
    """
    @property
    def fieldnames(self):
        raw_field_names = super().fieldnames
        return [field_name.strip().lower() for field_name in raw_field_names]


def load_records_from_uploaded_csv(csv_file, field_names, optional_fields=frozenset()):
    """
    Loads a CSV file. See `load_records_from_csv` for details.

    Arguments:
        csv_file (UploadedFile): CSV file uploaded in a POST call.
        field_names (set[str])
    """
    contents = csv_file.read().decode('utf-8')
    return load_records_from_csv(contents, field_names, optional_fields)


def load_records_from_csv(csv_string, field_names, optional_fields=frozenset()):
    """
    Loads a CSV string into a list of dicts, with `field_names` as keys.

    CSV row headers must be a superset of `field_names`.
    Extra row headers are removed.

    Arguments:
        csv_string (str)
        field_names (set[str])

    Returns: list[dict]

    Raises: ValidationError if the CSV does not have the required fields.
    """
    row_iter = csv_string.splitlines()
    reader = StrippedLowercaseFieldNamesDictReader(row_iter)
    required_fields = field_names - set(optional_fields)
    missing_fields = required_fields - set(reader.fieldnames)

    if missing_fields:
        raise ValidationError(
            "CSV is missing headers [{}]".format(", ".join(missing_fields))
        )
    records = []
    for n, row in enumerate(reader, 1):
        if None in row or not all(row[field] for field in required_fields):
            raise ValidationError(
                "CSV is missing data at row #{}. Required fields are [{}].".format(
                    n, ", ".join(field_names)
                )
            )
        stripped_row = {
            field: val.strip()
            for field, val in row.items()
            if field in field_names  # Drop not-requested fields.
        }
        records.append(stripped_row)
    return records
