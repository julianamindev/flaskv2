# These are non-Dashboard items

side_nav_items = {
    "Utilities": {
        "AWS": {
            "ref": "collapseAWS",
            "icon": "fas fa-cloud",
            "child_links": [
                {
                    "text": "LARS-to-AWS",
                    "route": "web.home.dashboard",
                },
                {
                    "text": "S3 LARS Builds",
                    "route": "web.home.dashboard",
                },
                {
                    "text": "Stacks View",
                    "route": "web.home.dashboard",
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
                    "route": "web.home.dashboard",
                },
                {
                    "text": "Register",
                    "route": "web.user.register",
                },
            ]
        },
        ".38 Bastion": {
            "ref": "collapseBastion",
            "icon": "fas fa-laptop-code",
            "child_links": [
                {
                    "text": "Task Scheduler Jobs",
                    "route": "web.home.dashboard",
                }
            ]
        }
    },
}