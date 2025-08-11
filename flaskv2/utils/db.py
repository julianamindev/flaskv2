from sqlalchemy.exc import SQLAlchemyError
from flaskv2 import db

def safe_commit():
    """
    Attempts to commit the current DB session.
    Rolls back and logs if there's an error.
    
    :param context: Description of what is being committed (for logging)
    :return: True if commit succeeded, False otherwise
    """

    try:
        db.session.commit()
        return True
    except SQLAlchemyError as e:
        db.session.rollback()
        print("f[DB COMMIT FAILED] Error: {e}")
        return False