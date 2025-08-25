# These are non-Dashboard items

side_nav_items = {
    "Utilities": {
        "AWS": {
            "ref": "collapseAWS",
            "icon": "fas fa-cloud",
            "child_links": [
                {
                    "text": "LARS-to-AWS",
                    "route": "main.lars2aws",
                },
                {
                    "text": "S3 LARS Builds",
                    "route": "main.s3_builds",
                },
                {
                    "text": "Stacks View",
                    "route": "main.instances",
                },
            ]
        },
    },

    ## Only root and admin users have access to this
    "Admin": {
        "User Management": {
            "ref": "collapseUserMgmt",
            "icon": "fas fa-user",
            "child_links": [
                {
                    "text": "Users List",
                    "route": "main.user_list",
                },
                {
                    "text": "Register",
                    "route": "users.register",
                },
            ]
        },
        ".38 Bastion": {
            "ref": "collapseBastion",
            "icon": "fas fa-laptop-code",
            "child_links": [
                {
                    "text": "Task Scheduler Jobs",
                    "route": "main.task_scheduler_list",
                }
            ]
        }
    },
}